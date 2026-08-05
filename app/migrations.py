from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.orm import Session

from app.classifier import normalize
from app.config import settings
from app.database import Base
from app.models import Article, DashboardUser, SystemMigration, UserKeyword


DEFAULT_KEYWORDS = [
    "Instituto Carioca", "esporte e lazer", "corrupção", "emenda parlamentar",
    "emendas parlamentares", "político corrupto", "políticos corruptos",
    "empresa que investe em ONG", "empresas que investem em ONG",
    "empresa que investe no meio ambiente", "empresas que investem no meio ambiente",
    "empresa que investe em esporte", "empresas que investem em esporte",
    "Lei Rouanet", "Lei Rounet", "lei de incentivo ao esporte", "Prefeitura de Maricá",
    "Movimento Cultural Social",
]


def searchable_text(title: str | None, body: str | None, source: str | None, journalist: str | None) -> str:
    # Padding keeps short location tokens such as "rj" searchable by word-like boundaries.
    return f" {normalize(' '.join(filter(None, [title, body, source, journalist])))} "


def _add_legacy_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    statements: list[str] = []
    if "articles" in tables:
        article_columns = {column["name"] for column in inspector.get_columns("articles")}
        if "searchable_text" not in article_columns:
            statements.append("ALTER TABLE articles ADD COLUMN searchable_text TEXT NULL")
    if "dashboard_users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("dashboard_users")}
        if "email" not in user_columns:
            statements.append("ALTER TABLE dashboard_users ADD COLUMN email VARCHAR(254) NULL")
        if "email_verified" not in user_columns:
            statements.append("ALTER TABLE dashboard_users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE")
        if "can_send_external_email" not in user_columns:
            statements.append("ALTER TABLE dashboard_users ADD COLUMN can_send_external_email BOOLEAN NOT NULL DEFAULT FALSE")
    if "email_schedules" in tables:
        schedule_columns = {column["name"] for column in inspector.get_columns("email_schedules")}
        if "recipient_email" not in schedule_columns:
            statements.append("ALTER TABLE email_schedules ADD COLUMN recipient_email VARCHAR(254) NULL")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


def _backfill_searchable_text(db: Session, batch_size: int = 500) -> int:
    changed = 0
    while True:
        rows = db.execute(
            select(Article.id, Article.title, Article.body, Article.source, Article.journalist)
            .where((Article.searchable_text.is_(None)) | (Article.searchable_text == ""))
            .limit(batch_size)
        ).all()
        if not rows:
            break
        for row in rows:
            db.execute(
                update(Article)
                .where(Article.id == row.id)
                .values(searchable_text=searchable_text(row.title, row.body, row.source, row.journalist))
            )
        db.commit()
        changed += len(rows)
    return changed


def _seed_keywords(db: Session, user_id: int) -> None:
    existing = {
        value.casefold()
        for value in db.scalars(select(UserKeyword.keyword).where(UserKeyword.user_id == user_id))
    }
    for keyword in DEFAULT_KEYWORDS:
        if keyword.casefold() not in existing:
            db.add(UserKeyword(user_id=user_id, keyword=keyword))
    db.flush()


def _bootstrap_users(db: Session) -> None:
    from app.auth import hash_password

    cfg = settings()
    first_user = db.scalar(select(DashboardUser.id).limit(1))
    if first_user is None and cfg.dashboard_password.strip():
        username = cfg.dashboard_user.strip().lower()
        user = DashboardUser(
            username=username,
            display_name="Administrador MCS",
            password_hash=hash_password(cfg.dashboard_password),
            is_admin=True,
            email_verified=True,
        )
        db.add(user)
        db.flush()
        _seed_keywords(db, user.id)

    default_migration = db.get(SystemMigration, "default_keywords_v2")
    if default_migration is None:
        for user_id in db.scalars(select(DashboardUser.id)):
            _seed_keywords(db, user_id)
        db.add(SystemMigration(migration_key="default_keywords_v2"))

    alert_migration = db.get(SystemMigration, "institutional_alert_keywords_v2")
    if alert_migration is None:
        db.query(UserKeyword).filter(UserKeyword.keyword.ilike("mcs")).delete(synchronize_session=False)
        for user_id in db.scalars(select(DashboardUser.id)):
            exists = db.scalar(
                select(UserKeyword.id).where(
                    UserKeyword.user_id == user_id,
                    UserKeyword.keyword == "Instituto Carioca",
                )
            )
            if exists is None:
                db.add(UserKeyword(user_id=user_id, keyword="Instituto Carioca"))
        db.add(SystemMigration(migration_key="institutional_alert_keywords_v2"))
    db.commit()


def initialize_schema(engine: Engine) -> dict[str, int]:
    # Legacy databases must receive columns before SQLAlchemy creates/checks indexes.
    _add_legacy_columns(engine)
    Base.metadata.create_all(engine)
    # create_all does not add new indexes to tables that already existed.
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(engine, checkfirst=True)
    with Session(engine) as db:
        _bootstrap_users(db)
        from app.auth import enforce_configured_owner

        enforce_configured_owner(db)
        now = datetime.now().replace(microsecond=0)
        db.execute(text("DELETE FROM dashboard_sessions WHERE expires_at < :now"), {"now": now})
        db.execute(text("DELETE FROM password_reset_tokens WHERE expires_at < :now OR used_at IS NOT NULL"), {"now": now})
        db.commit()
        backfilled = _backfill_searchable_text(db)
    return {"searchable_text_backfilled": backfilled}
