import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Classification, McsAlert
from app.services import (
    _deduplicate_items,
    backfill_mcs_alerts,
    collect_mcs_alerts,
    mcs_alert_terms,
    prune_mcs_alerts,
    prune_expired,
    recent_stats,
    save_item,
)


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


def test_save_item_cria_alerta_global_mcs_e_nao_duplica(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()
    item = _item(
        "MCS anuncia novo projeto cultural",
        "O Movimento Cultural Social apresentou a iniciativa nesta manhã.",
        "https://example.com/mcs-projeto",
    )

    with Session(engine) as db:
        assert save_item(db, item) is not None
        assert save_item(db, item) is None
        alert = db.scalar(select(McsAlert))
        assert alert is not None
        assert json.loads(alert.matched_terms_json) == ["Movimento Cultural Social", "MCS"]
        assert "MCS" in alert.match_excerpt
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 1


def test_alerta_mcs_preserva_snapshot_apos_noticia_expirar(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()

    with Session(engine) as db:
        article = save_item(
            db,
            _item(
                "Movimento Cultural Social realiza encontro",
                "A programação reuniu representantes locais.",
                "https://example.com/encontro-mcs",
            ),
        )
        article.published_at = datetime.now(timezone.utc) - timedelta(hours=73)
        db.commit()

        assert prune_expired(db) == 1
        assert db.scalar(select(func.count()).select_from(Article)) == 0
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 1


def test_backfill_de_alertas_mcs_e_idempotente():
    engine = _database()
    with Session(engine) as db:
        article = Article(
            title="Ações do MCS ganham destaque",
            body="A agenda cultural foi apresentada.",
            url="https://example.com/backfill-mcs",
            source="Portal A",
            section="cultura",
            published_at=datetime.now(timezone.utc),
        )
        article.classification = Classification(
            risk_score=0,
            tone="positivo",
            impact_score=5,
            matched_keywords="[]",
            evidence="[]",
        )
        db.add(article)
        db.commit()

        assert backfill_mcs_alerts(db)["alertas_criados"] == 1
        assert backfill_mcs_alerts(db)["alertas_criados"] == 0


def test_detector_de_alertas_mcs_respeita_fronteiras_e_remove_identificadores():
    positives = [
        ("Movimento Cultural Social lança edital", ""),
        ("MOVIMENTO   CULTURAL\nSOCIAL amplia ações", ""),
        ("MCS anuncia programação", ""),
        ("Agenda do (MCS) foi divulgada", ""),
        ("Parceria MCS-RJ começa hoje", ""),
        ("mcs apresenta novo projeto", ""),
    ]
    negatives = [
        ("AMCS apresenta balanço", ""),
        ("MCSA anuncia resultado", ""),
        ("MCS2 será atualizado", ""),
        ("Código MCS_2026 foi publicado", ""),
        ("Leia em https://mcs.org/noticia", ""),
        ("Contato imprensa@mcs.org", ""),
        ("Acesse portal.MCS.org para mais detalhes", ""),
        ("MCS|Marcus Corp|Preço:24.840|Var. %:+0.360 - TradingKey", ""),
        ("Método Monte Carlo (MCS) acelera a simulação", ""),
        ("Siga @MCS e #MCS", ""),
    ]

    assert all(mcs_alert_terms(title, body) for title, body in positives)
    assert all(not mcs_alert_terms(title, body) for title, body in negatives)


def test_candidato_global_e_enriquecido_antes_da_decisao(monkeypatch):
    def enrich_with_alert(item):
        item["body"] = "A reportagem cita o Movimento Cultural Social no texto completo."
        return item

    monkeypatch.setattr("app.services.enrich", enrich_with_alert)
    engine = _database()
    item = _item(
        "Programação cultural é divulgada",
        "Leia os detalhes da agenda.",
        "https://example.com/texto-completo-mcs",
    )
    item["_global_alert_candidate"] = True
    item["_skip_enrich"] = False

    with Session(engine) as db:
        assert save_item(db, item) is not None
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 1


def test_deduplicacao_preserva_metadados_da_consulta_prioritaria():
    priority = {
        "url": "https://example.com/mesma-noticia",
        "body": "Resumo prioritário",
        "_global_alert_candidate": True,
        "_skip_enrich": False,
    }
    common = {
        "url": "https://example.com/mesma-noticia",
        "body": "Resumo comum mais longo, retornado por outra consulta.",
        "_global_alert_candidate": False,
        "_skip_enrich": True,
    }

    result = _deduplicate_items([priority, common])

    assert len(result) == 1
    assert result[0]["_global_alert_candidate"] is True
    assert result[0]["_skip_enrich"] is False
    assert result[0]["body"] == "Resumo prioritário"


def test_candidato_global_cria_alerta_quando_artigo_ja_existe(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()
    base = _item(
        "Projeto cultural recebe investimento",
        "A iniciativa recebeu patrocínio para novas atividades.",
        "https://example.com/artigo-ja-existente",
    )
    candidate = dict(base)
    candidate["body"] = "O Movimento Cultural Social denuncia fraude e corrupção na iniciativa."
    candidate["_global_alert_candidate"] = True
    candidate["_skip_enrich"] = True

    with Session(engine) as db:
        assert save_item(db, base, ["patrocínio"]) is not None
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 0

        assert save_item(db, candidate, ["MCS"]) is None
        alert = db.scalar(select(McsAlert))
        assert alert is not None
        assert "Movimento Cultural Social" in alert.match_excerpt
        assert alert.risk_score == 10


def test_coleta_rapida_recupera_alerta_de_item_rss_ja_existente(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()
    base = _item(
        "Projeto cultural recebe patrocínio",
        "A iniciativa abriu novas atividades.",
        "https://example.com/rss-ja-existente",
    )
    candidate = dict(base)
    candidate["body"] = "O MCS confirmou participação no evento."
    monkeypatch.setattr("app.services.rss_items", lambda: [candidate])
    monkeypatch.setattr("app.services.google_news_items", lambda **kwargs: [])

    with Session(engine) as db:
        assert save_item(db, base, ["patrocínio"]) is not None

        result = collect_mcs_alerts(db)

        assert result["novos"] == 1
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 1


def test_modo_exclusivo_de_alerta_nao_salva_noticia_de_outro_tema(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()
    item = _item(
        "Operação investiga corrupção",
        "A apuração trata de fraude em contrato público.",
        "https://example.com/sem-mcs",
    )
    item["_global_alert_candidate"] = True
    item["_skip_enrich"] = True

    with Session(engine) as db:
        assert save_item(db, item, ["MCS"], alert_only=True) is None
        assert db.scalar(select(func.count()).select_from(Article)) == 0


def test_alertas_com_mais_de_90_dias_sao_removidos(monkeypatch):
    monkeypatch.setattr("app.services.enrich", lambda item: item)
    engine = _database()

    with Session(engine) as db:
        save_item(
            db,
            _item(
                "MCS apresenta balanço",
                "Movimento Cultural Social detalha as atividades.",
                "https://example.com/mcs-antigo",
            ),
        )
        alert = db.scalar(select(McsAlert))
        alert.detected_at = datetime.now(timezone.utc) - timedelta(days=91)
        db.commit()

        assert prune_mcs_alerts(db) == 1
        assert db.scalar(select(func.count()).select_from(McsAlert)) == 0


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


def test_recent_stats_prioriza_relevancia_em_abrangencia_nacional():
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

        assert highlights[0]["abrangencia"] == "nacional"
        assert {item["abrangencia"] for item in highlights[1:]} == {"marica", "estado_rj"}
