from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, DateTime, Integer, BigInteger, Float, ForeignKey, Index,
    Boolean, UniqueConstraint, event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def now(): return datetime.now(timezone.utc)

class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("idx_articles_dashboard_period", "published_at", "source", "section"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), index=True)
    section: Mapped[str] = mapped_column(String(100), default="nao_identificada", index=True)
    journalist: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    journalist_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    searchable_text: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped["Classification"] = relationship(back_populates="article", cascade="all, delete-orphan", uselist=False)

class Classification(Base):
    __tablename__ = "classifications"
    __table_args__ = (
        Index("idx_classifications_dashboard", "risk_score", "tone", "article_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), unique=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    tone: Mapped[str] = mapped_column(String(30), default="neutro", index=True)
    impact_score: Mapped[float] = mapped_column(Float, default=0)
    matched_keywords: Mapped[str] = mapped_column(Text, default="[]")
    evidence: Mapped[str] = mapped_column(Text, default="[]")
    article: Mapped[Article] = relationship(back_populates="classification")

class McsAlert(Base):
    __tablename__ = "mcs_alerts"
    __table_args__ = (Index("idx_mcs_alert_detected", "detected_at", "id"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    article_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now,
        server_default=func.now(),
    )
    matched_terms_json: Mapped[str] = mapped_column(Text)
    match_excerpt: Mapped[str | None] = mapped_column(String(600), nullable=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    impact_score: Mapped[float] = mapped_column(Float, default=0)


class DashboardUser(Base):
    __tablename__ = "dashboard_users"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    can_send_external_email: Mapped[bool] = mapped_column(Boolean, default=False)
    can_send_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class DashboardSession(Base):
    __tablename__ = "dashboard_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class UserKeyword(Base):
    __tablename__ = "user_keywords"
    __table_args__ = (UniqueConstraint("user_id", "keyword", name="uq_user_keyword"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), index=True)
    keyword: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class SystemMigration(Base):
    __tablename__ = "system_migrations"

    migration_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class UserMcsAlertRead(Base):
    __tablename__ = "user_mcs_alert_reads"
    __table_args__ = (Index("idx_mcs_alert_read_alert", "alert_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("mcs_alerts.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class EmailSchedule(Base):
    __tablename__ = "email_schedules"
    __table_args__ = (Index("idx_email_schedule_due", "status", "scheduled_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dashboard_users.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keywords_json: Mapped[str] = mapped_column(Text)
    recipient_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


@event.listens_for(Article, "before_insert")
@event.listens_for(Article, "before_update")
def populate_article_searchable_text(_mapper, _connection, article: Article) -> None:
    from app.classifier import normalize

    article.searchable_text = f" {normalize(' '.join(filter(None, [
        article.title, article.body, article.source, article.journalist,
    ])))} "
