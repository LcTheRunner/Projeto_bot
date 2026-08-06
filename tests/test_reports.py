import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Classification, DashboardUser, UserKeyword
import app.reports as reports
from app.reports import daily_report_accounts, parse_recipients, render_report, render_text_report, report_data


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


def test_boletim_diario_carrega_cada_conta_com_suas_proprias_palavras_em_uma_lista():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        first = DashboardUser(
            username="leo",
            display_name="Leo",
            email="leo@example.com",
            email_verified=True,
            password_hash="hash",
            active=True,
        )
        second = DashboardUser(
            username="maria",
            display_name="Maria",
            email="maria@example.com",
            email_verified=True,
            password_hash="hash",
            active=True,
        )
        disabled = DashboardUser(
            username="inativo",
            display_name="Inativo",
            email="inativo@example.com",
            email_verified=True,
            password_hash="hash",
            active=False,
        )
        db.add_all([first, second, disabled])
        db.flush()
        db.add_all([
            UserKeyword(user_id=first.id, keyword="corrupção"),
            UserKeyword(user_id=first.id, keyword="ONG"),
            UserKeyword(user_id=second.id, keyword="esporte"),
            UserKeyword(user_id=disabled.id, keyword="não enviar"),
        ])
        db.commit()

        accounts = daily_report_accounts(db)

        assert accounts == [
            {
                "id": first.id,
                "display_name": "Leo",
                "email": "leo@example.com",
                "keywords": ["ONG", "corrupção"],
            },
            {
                "id": second.id,
                "display_name": "Maria",
                "email": "maria@example.com",
                "keywords": ["esporte"],
            },
        ]


def test_boletim_diario_envia_conteudo_isolado_por_conta(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    delivered = []

    class FakeSmtp:
        def send_message(self, message, to_addrs):
            delivered.append((to_addrs, message))

    @contextmanager
    def fake_smtp_session():
        yield FakeSmtp()

    monkeypatch.setattr(reports, "settings", lambda: SimpleNamespace(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        report_from="radar@example.com",
        report_to="",
    ))
    monkeypatch.setattr(reports, "_smtp_session", fake_smtp_session)

    with Session(engine) as db:
        leo = DashboardUser(
            username="leo", display_name="Leo", email="leo@example.com",
            email_verified=True, password_hash="hash", active=True,
        )
        maria = DashboardUser(
            username="maria", display_name="Maria", email="maria@example.com",
            email_verified=True, password_hash="hash", active=True,
        )
        db.add_all([leo, maria])
        db.flush()
        db.add_all([
            UserKeyword(user_id=leo.id, keyword="corrupção"),
            UserKeyword(user_id=maria.id, keyword="esporte"),
        ])
        corruption = Article(
            title="Corrupção é investigada",
            body="Polícia Federal apura o caso.",
            url="https://example.com/corrupcao",
            source="Portal A",
            published_at=datetime.now(timezone.utc),
        )
        corruption.classification = Classification(
            risk_score=10, tone="negativo", impact_score=9,
            matched_keywords='["corrupção"]', evidence="[]",
        )
        sport = Article(
            title="Projeto de esporte recebe investimento",
            body="Nova iniciativa de lazer.",
            url="https://example.com/esporte",
            source="Portal B",
            published_at=datetime.now(timezone.utc),
        )
        sport.classification = Classification(
            risk_score=0, tone="positivo", impact_score=4,
            matched_keywords='["esporte"]', evidence="[]",
        )
        db.add_all([corruption, sport])
        db.commit()

        result = reports.send_daily_user_reports(db)

    assert result["enviados"] == 2
    assert result["consultas_de_conteudo"] == 2
    messages = {
        recipients[0]: message.get_body(preferencelist=("plain",)).get_content()
        for recipients, message in delivered
    }
    assert "Corrupção é investigada" in messages["leo@example.com"]
    assert "Projeto de esporte" not in messages["leo@example.com"]
    assert "Projeto de esporte" in messages["maria@example.com"]
    assert "Corrupção é investigada" not in messages["maria@example.com"]
