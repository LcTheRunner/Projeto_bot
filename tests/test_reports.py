import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Classification
from app.reports import parse_recipients, render_report, render_text_report


def test_relatorio_inclui_janela_prioridade_e_url():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        article = Article(
            title="Empresa anuncia investimento social no esporte",
            body="Patrocínio para projeto esportivo.",
            url="https://example.com/noticia-importante",
            source="Portal Nacional",
            section="investimento_social_ambiental",
            published_at=datetime.now(timezone.utc),
        )
        article.classification = Classification(
            risk_score=7,
            tone="negativo",
            impact_score=8.5,
            matched_keywords=json.dumps(["investimento social", "esporte"]),
            evidence="[]",
        )
        db.add(article)
        db.commit()

        html = render_report(db)
        text = render_text_report(db)

        assert "Notícias das últimas 72 horas" in html
        assert "Notícias mais importantes" in html
        assert "https://example.com/noticia-importante" in html
        assert "Abrir notícia" in html
        assert "https://example.com/noticia-importante" in text


def test_multiplos_destinatarios_aceitam_virgula_e_ponto_e_virgula():
    recipients = parse_recipients(
        "primeiro@example.com; segundo@example.com,\nterceiro@example.com"
    )

    assert recipients == [
        "primeiro@example.com",
        "segundo@example.com",
        "terceiro@example.com",
    ]
