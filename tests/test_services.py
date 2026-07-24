import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Classification
from app.services import recent_stats, save_item


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _item(title: str, body: str, url: str):
    return {
        "title": title,
        "body": body,
        "url": url,
        "source": "Fonte de teste",
        "published_at": datetime.now(timezone.utc),
    }


def test_save_item_descarta_noticia_fora_do_escopo(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()

    with Session(engine) as db:
        saved = save_item(
            db,
            _item(
                "Time vence campeonato de futebol",
                "A torcida comemorou o resultado no estádio.",
                "https://example.com/futebol",
            ),
        )

        assert saved is None
        assert db.scalar(select(func.count()).select_from(Article)) == 0


def test_save_item_persiste_e_classifica_noticia_relevante(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()

    with Session(engine) as db:
        saved = save_item(
            db,
            _item(
                "Empresa anuncia patrocínio a ONG de esporte",
                "O investimento social financiará projetos para jovens.",
                "https://example.com/patrocinio",
            ),
        )

        assert saved is not None
        assert saved.section == "investimento_social_ambiental"
        assert saved.classification is not None
        assert db.scalar(select(func.count()).select_from(Article)) == 1


def test_save_item_descarta_noticia_com_mais_de_72_horas(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()
    item = _item(
        "Corrupção é investigada",
        "Operação apura desvio de recursos.",
        "https://example.com/antiga",
    )
    item["published_at"] = datetime.now(timezone.utc) - timedelta(hours=73)

    with Session(engine) as db:
        assert save_item(db, item) is None
        assert db.scalar(select(func.count()).select_from(Article)) == 0


def test_recent_stats_prioriza_risco_e_exclui_noticia_antiga():
    engine = _database()
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        recent = Article(
            title="Operação investiga corrupção",
            body="Notícia recente.",
            url="https://example.com/recente",
            source="Portal A",
            section="integridade_corrupcao",
            published_at=now - timedelta(hours=2),
        )
        recent.classification = Classification(
            risk_score=10,
            tone="negativo",
            impact_score=9,
            matched_keywords=json.dumps(["corrupção"]),
            evidence="[]",
        )
        old = Article(
            title="Emenda parlamentar antiga",
            body="Notícia antiga.",
            url="https://example.com/antiga-estatistica",
            source="Portal B",
            section="emendas_parlamentares",
            published_at=now - timedelta(hours=73),
        )
        old.classification = Classification(
            risk_score=0,
            tone="neutro",
            impact_score=2,
            matched_keywords=json.dumps(["emenda parlamentar"]),
            evidence="[]",
        )
        db.add_all([recent, old])
        db.commit()

        stats = recent_stats(db)

        assert stats["periodo_horas"] == 72
        assert stats["total"] == 1
        assert stats["principais"][0]["url"] == "https://example.com/recente"
        assert stats["principais"][0]["prioridade"] == "crítica"


def test_recent_stats_prioriza_marica_e_estado_do_rj_antes_de_nacional():
    engine = _database()
    now = datetime.now(timezone.utc)

    def article(title, url, source, risk):
        item = Article(
            title=title,
            body="Notícia monitorada.",
            url=url,
            source=source,
            section="integridade_corrupcao",
            published_at=now,
        )
        item.classification = Classification(
            risk_score=risk,
            tone="negativo" if risk else "neutro",
            impact_score=10 if risk else 2,
            matched_keywords=json.dumps(["corrupção"]),
            evidence="[]",
        )
        return item

    with Session(engine) as db:
        db.add_all([
            article("Caso nacional de grande risco", "https://example.com/nacional", "Portal Nacional", 10),
            article("Projeto esportivo em Maricá", "https://example.com/marica", "Prefeitura de Maricá", 0),
            article("Edital para organizações de Niterói", "https://example.com/rj", "Portal RJ", 0),
        ])
        db.commit()

        highlights = recent_stats(db)["principais"]

        assert [item["abrangencia"] for item in highlights] == ["marica", "estado_rj", "nacional"]
