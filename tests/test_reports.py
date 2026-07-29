import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Classification
from app.reports import parse_recipients, render_report, render_text_report, report_data


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

        assert "O que merece atenção hoje" in html
        assert "até 6 notícias recentes" in html
        assert "https://example.com/noticia-importante" in html
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


def test_boletim_respeita_palavras_risco_e_limite_de_seis_noticias():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for index in range(8):
            article = Article(
                title=f"Corrupção em investigação pública {index}",
                body="A apuração encontrou indícios relacionados ao caso.",
                url=f"https://example.com/corrupcao-{index}",
                source="Portal Nacional",
                section="integridade_corrupcao",
                published_at=datetime.now(timezone.utc),
            )
            article.classification = Classification(
                risk_score=10,
                tone="negativo",
                impact_score=9,
                matched_keywords=json.dumps(["corrupção"]),
                evidence="[]",
            )
            db.add(article)
        unrelated = Article(
            title="Agenda cultural da cidade",
            body="Programação de lazer para o fim de semana.",
            url="https://example.com/cultura",
            source="Portal Cultural",
            section="cultura_incentivo",
            published_at=datetime.now(timezone.utc),
        )
        unrelated.classification = Classification(
            risk_score=5,
            tone="neutro",
            impact_score=4,
            matched_keywords=json.dumps(["cultura"]),
            evidence="[]",
        )
        db.add(unrelated)
        db.commit()

        data = report_data(db, terms=["corrupção"], risk=10, hours=24)

        assert data["total"] == 8
        assert len(data["principais"]) == 6
        assert all(item["risco"] == 10 for item in data["principais"])
