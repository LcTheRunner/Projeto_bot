"""Create a disposable 12k-row dataset and measure dashboard queries.

Safety: the configured database name must end with ``_benchmark``. The caller is
responsible for creating and dropping that disposable MariaDB database.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.dashboard_service import OverviewOptions, clear_dashboard_cache, overview
from app.database import Base, engine
from app.migrations import searchable_text
from app.models import Article, Classification, DashboardUser, UserKeyword


def measured(call):
    started = time.perf_counter()
    result = call()
    return result, round((time.perf_counter() - started) * 1000, 1)


def main() -> None:
    url = make_url(str(engine.url))
    database = url.database or ""
    safe_mariadb = database.endswith("_benchmark")
    safe_sqlite = url.drivername.startswith("sqlite") and database == "/tmp/cadu_dashboard_benchmark.db"
    if not (safe_mariadb or safe_sqlite):
        raise RuntimeError("Banco de benchmark inválido")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now()
    with Session(engine) as db:
        user = DashboardUser(
            username="benchmark",
            display_name="Benchmark",
            email="benchmark@example.com",
            email_verified=True,
            password_hash=hash_password("benchmark"),
            is_admin=True,
        )
        db.add(user)
        db.flush()
        db.add_all([
            UserKeyword(user_id=user.id, keyword="corrupção"),
            UserKeyword(user_id=user.id, keyword="Instituto Carioca"),
        ])
        articles = []
        for index in range(12_000):
            title = f"Notícia {index} sobre corrupção e Instituto Carioca"
            body = "Polícia Federal investiga organização social e emendas parlamentares. " * 3
            source = f"Veículo {index % 40:02d}"
            articles.append({
                "url": f"https://benchmark.invalid/{index}",
                "title": title,
                "body": body,
                "source": source,
                "section": "politica" if index % 2 else "terceiro_setor",
                "published_at": now - timedelta(minutes=index % 10_000),
                "collected_at": now,
                "searchable_text": searchable_text(title, body, source, None),
            })
        db.execute(insert(Article), articles)
        ids = list(db.scalars(select(Article.id).order_by(Article.id)))
        db.execute(insert(Classification), [{
            "article_id": article_id,
            "risk_score": (0, 5, 10)[index % 3],
            "tone": ("neutro", "quase_negativo", "negativo")[index % 3],
            "impact_score": float(index % 11),
            "matched_keywords": '["corrupção", "Instituto Carioca"]',
            "evidence": "[]",
        } for index, article_id in enumerate(ids)])
        db.commit()

        clear_dashboard_cache()
        normal, normal_ms = measured(lambda: overview(db, user.id, OverviewOptions(days=365, page_size=50)))
        cached, cached_ms = measured(lambda: overview(db, user.id, OverviewOptions(days=365, page_size=50)))
        filtered, filtered_ms = measured(lambda: overview(
            db, user.id, OverviewOptions(days=365, risks=(10,), query="Polícia Federal", page_size=50)
        ))
        print(json.dumps({
            "rows": normal["kpis"]["articles"],
            "page_items": len(normal["articles"]),
            "cold_ms": normal_ms,
            "cached_ms": cached_ms,
            "cache_hit": cached["cache"]["hit"],
            "filtered_rows": filtered["kpis"]["articles"],
            "filtered_ms": filtered_ms,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
