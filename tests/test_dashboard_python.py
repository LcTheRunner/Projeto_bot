from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import hash_password, router as auth_router, verify_password
from app.cache import TtlCache
from app.dashboard_routes import router as dashboard_router
from app.dashboard_service import OverviewOptions, clear_dashboard_cache, overview
from app.database import Base, get_db
from app.migrations import searchable_text
from app.models import Article, Classification, DashboardUser, McsAlert, UserKeyword


def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def seed(engine):
    with Session(engine) as db:
        user = DashboardUser(
            username="admin",
            display_name="Admin",
            email="admin@example.com",
            email_verified=True,
            password_hash=hash_password("123456"),
            is_admin=True,
        )
        db.add(user)
        db.flush()
        db.add(UserKeyword(user_id=user.id, keyword="corrupção"))
        for index, risk in enumerate((10, 5, 0), 1):
            title = f"Caso de corrupção número {index}"
            article = Article(
                url=f"https://example.com/{index}",
                title=title,
                body="Polícia Federal investiga organização",
                source="Fonte A" if index < 3 else "Fonte B",
                section="politica",
                published_at=datetime.now() - timedelta(hours=index),
                searchable_text=searchable_text(title, "Polícia Federal investiga organização", "Fonte A", None),
            )
            article.classification = Classification(
                risk_score=risk,
                tone="negativo" if risk else "neutro",
                impact_score=float(risk),
                matched_keywords='["corrupção"]',
                evidence="[]",
            )
            db.add(article)
        db.commit()
        return user.id


def test_java_bcrypt_hashes_remain_compatible():
    generated = hash_password("segredo")
    java_prefix = "$2a$" + generated[4:]
    assert verify_password("segredo", java_prefix)
    assert not verify_password("errada", java_prefix)


def test_bounded_cache_returns_copies():
    cache = TtlCache(ttl_seconds=10, max_entries=1)
    cache.set("a", {"value": []})
    first = cache.get("a")
    first["value"].append(1)
    assert cache.get("a") == {"value": []}
    cache.set("b", 2)
    assert cache.get("a") is None


def test_overview_filters_in_database_and_paginates():
    engine = database()
    user_id = seed(engine)
    clear_dashboard_cache()
    with Session(engine) as db:
        result = overview(db, user_id, OverviewOptions(page_size=2))
        assert result["kpis"] == {
            "articles": 3,
            "sources": 2,
            "risk10": 1,
            "risk5": 1,
            "averageImpact": 5.0,
            "instagram": 0,
        }
        assert len(result["articles"]) == 2
        assert result["pagination"]["totalPages"] == 2
        assert result["byRisk"] == [
            {"label": "Risco 0", "value": 1},
            {"label": "Risco 5", "value": 1},
            {"label": "Risco 10", "value": 1},
        ]
        filtered = overview(db, user_id, OverviewOptions(risks=(10,)))
        assert filtered["kpis"]["articles"] == 1
        assert filtered["articles"][0]["risk"] == 10


def test_http_contract_login_dashboard_and_keywords():
    engine = database()
    seed(engine)
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(dashboard_router)

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    unauthenticated = client.get("/api/dashboard/overview")
    assert unauthenticated.status_code == 401
    assert "detail" in unauthenticated.json()

    login = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert login.status_code == 200
    assert login.json()["displayName"] == "Admin"
    assert login.cookies.get("mcs_session")

    response = client.get("/api/dashboard/overview", params={"risk": 10, "pageSize": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["articles"] == 1
    assert set(payload) >= {
        "periodDays", "generatedAt", "kpis", "byRisk", "byTone", "bySource",
        "bySection", "byKeyword", "timeline", "articles", "pagination",
    }

    batch = client.post("/api/dashboard/keywords/batch", json={"text": "ONG; Meio ambiente; ONG"})
    assert batch.status_code == 200
    assert batch.json() == {"received": 3, "added": 2, "ignored": 1}
    keywords = client.get("/api/dashboard/keywords").json()
    assert {item["keyword"] for item in keywords} == {"corrupção", "ONG", "Meio ambiente"}

    scheduled_at = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    schedule = client.post("/api/dashboard/email-schedules", json={
        "scheduledAt": scheduled_at,
        "risk": 10,
        "keywords": ["corrupção"],
        "recipientEmail": None,
    })
    assert schedule.status_code == 200
    schedules = client.get("/api/dashboard/email-schedules").json()
    assert schedules[0]["risk"] == 10
    assert schedules[0]["status"] == "PENDING"
    assert client.delete(f"/api/dashboard/email-schedules/{schedule.json()['id']}").status_code == 200


def test_alert_contract_and_read_state():
    engine = database()
    seed(engine)
    with Session(engine) as db:
        db.add(McsAlert(
            article_id=None,
            url_hash="a" * 64,
            title="Instituto Carioca em destaque",
            url="https://example.com/alerta",
            source="Fonte A",
            published_at=datetime.now(),
            detected_at=datetime.now() + timedelta(seconds=1),
            matched_terms_json='["Instituto Carioca"]',
            match_excerpt="Menção institucional",
            risk_score=5,
            impact_score=7.5,
        ))
        db.commit()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(dashboard_router)

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "123456"}).status_code == 200
    payload = client.get("/api/dashboard/alerts").json()
    assert payload["unreadCount"] == 1
    assert payload["items"][0]["matchedTerms"] == ["Instituto Carioca"]
    alert_id = payload["items"][0]["id"]
    assert client.put(f"/api/dashboard/alerts/{alert_id}/read").json() == {"unreadCount": 0}
    assert client.put("/api/dashboard/alerts/read-all").json() == {"unreadCount": 0}
