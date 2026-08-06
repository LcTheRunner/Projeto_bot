import smtplib
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.models import DashboardUser, UserKeyword
from app.services import recent_stats

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
EMAIL_NEWS_LIMIT = 6
SECTION_LABELS = {
    "marica_esporte": "Maricá e esporte",
    "instituto_carioca": "Instituto Carioca",
    "integridade_corrupcao": "Integridade e corrupção",
    "emendas_parlamentares": "Emendas parlamentares",
    "editais_oportunidades": "Editais e oportunidades",
    "cultura_incentivo": "Cultura e incentivo",
    "investimento_social_ambiental": "Investimento social e ambiental",
    "esporte_lazer": "Esporte e lazer",
    "nao_identificada": "Outros temas monitorados",
}


def parse_recipients(value: str) -> list[str]:
    recipients = []
    for address in re.split(r"[,;\n]+", value or ""):
        normalized = address.strip()
        if normalized and "@" in normalized and normalized not in recipients:
            recipients.append(normalized)
    return recipients


def _date(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(LOCAL_TZ).strftime("%d/%m/%Y às %H:%M")


def _label(value: str) -> str:
    return SECTION_LABELS.get(value, value.replace("_", " ").title())


def _filter_label(terms: list[str] | None, risk: int | None) -> str:
    pieces = []
    if terms:
        pieces.append(f"{len(terms)} palavra{'s' if len(terms) != 1 else ''}-chave")
    pieces.append("todos os riscos" if risk is None else f"risco {risk}")
    return " · ".join(pieces)


def _story(item: dict, index: int) -> str:
    risk_color = "#b42318" if item["risco"] == 10 else "#b54708" if item["risco"] == 5 else "#157f64"
    journalist = f" · {escape(item['jornalista'])}" if item.get("jornalista") else ""
    return f"""
      <tr><td style="padding:0 0 20px">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-top:1px solid #d9d6ce">
          <tr>
            <td width="38" valign="top" style="padding:18px 12px 0 0;color:#9a958a;font:700 12px Georgia,serif">{index:02d}</td>
            <td valign="top" style="padding:16px 0 0">
              <p style="margin:0 0 6px;color:{risk_color};font:700 10px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase">Risco {item['risco']} · impacto {item['impacto']:.1f}</p>
              <h2 style="margin:0 0 7px;font:700 19px/1.28 Georgia,serif">
                <a href="{escape(item['url'], quote=True)}" style="color:#18201f;text-decoration:none">{escape(item['titulo'])}</a>
              </h2>
              <p style="margin:0;color:#66645f;font:12px/1.5 Arial,sans-serif">{escape(item['veiculo'])}{journalist} · {_date(item['publicada_em'])}</p>
            </td>
          </tr>
        </table>
      </td></tr>"""


def report_data(db, terms: list[str] | None = None, risk: int | None = None, hours: int = 72) -> dict:
    return recent_stats(db, top_limit=EMAIL_NEWS_LIMIT, terms=terms, risk=risk, hours=hours)


def render_report(
    db,
    terms: list[str] | None = None,
    risk: int | None = None,
    recipient_name: str | None = None,
    hours: int = 72,
    stats: dict | None = None,
) -> str:
    stats = stats if stats is not None else report_data(db, terms, risk, hours)
    stories = "".join(_story(item, index) for index, item in enumerate(stats["principais"], 1))
    if not stories:
        stories = """
          <tr><td style="padding:26px;border:1px solid #d9d6ce;background:#fff;color:#66645f;font:14px/1.5 Arial,sans-serif">
            Nenhuma notícia correspondeu aos filtros deste envio.
          </td></tr>"""
    greeting = f"Olá, {escape(recipient_name)}." if recipient_name else "Boletim programado"
    generated_at = datetime.now(LOCAL_TZ).strftime("%d/%m/%Y · %H:%M")
    return f"""<!doctype html>
<html lang="pt-BR"><body style="margin:0;background:#eceae4;color:#18201f">
<div style="display:none;max-height:0;overflow:hidden">Seu recorte de monitoramento está pronto.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eceae4">
  <tr><td align="center" style="padding:24px 10px">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#f8f7f3;border:1px solid #d7d3c9">
      <tr><td style="padding:28px 30px 24px;border-top:5px solid #24473f">
        <table role="presentation" width="100%"><tr>
          <td><p style="margin:0;color:#24473f;font:700 11px Arial,sans-serif;letter-spacing:.15em;text-transform:uppercase">MCS · Radar de mídia</p></td>
          <td align="right" style="color:#77736b;font:11px Arial,sans-serif">{generated_at}</td>
        </tr></table>
        <h1 style="margin:22px 0 7px;font:700 32px/1.05 Georgia,serif;color:#18201f">O que merece atenção hoje</h1>
        <p style="margin:0;color:#66645f;font:14px/1.55 Arial,sans-serif">{greeting} Selecionamos até {EMAIL_NEWS_LIMIT} notícias recentes para uma leitura rápida e útil.</p>
      </td></tr>
      <tr><td style="padding:0 30px 24px">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#e7eee9;border-left:3px solid #24473f">
          <tr>
            <td style="padding:15px"><strong style="display:block;color:#24473f;font:700 22px Georgia,serif">{stats['total']}</strong><span style="color:#5f6864;font:11px Arial,sans-serif">notícias encontradas nas últimas {hours}h</span></td>
            <td style="padding:15px"><strong style="display:block;color:#9f2d25;font:700 22px Georgia,serif">{stats['por_risco'].get('10', 0)}</strong><span style="color:#5f6864;font:11px Arial,sans-serif">alertas de risco crítico</span></td>
          </tr>
        </table>
        <p style="margin:12px 0 0;color:#77736b;font:11px Arial,sans-serif">Recorte: {escape(_filter_label(terms, risk))}</p>
      </td></tr>
      <tr><td style="padding:0 30px 10px"><table role="presentation" width="100%">{stories}</table></td></tr>
      <tr><td style="padding:20px 30px;background:#24473f;color:#dbe5e0;font:11px/1.5 Arial,sans-serif;text-align:center">
        Envio automático da Central de Monitoramento do MCS<br>
        Ajuste ou cancele seus horários no painel.
      </td></tr>
    </table>
  </td></tr>
</table></body></html>"""


def render_text_report(
    db,
    terms: list[str] | None = None,
    risk: int | None = None,
    recipient_name: str | None = None,
    hours: int = 72,
    stats: dict | None = None,
) -> str:
    stats = stats if stats is not None else report_data(db, terms, risk, hours)
    lines = [
        "CENTRAL DE MONITORAMENTO DO MCS",
        f"{recipient_name + ', ' if recipient_name else ''}seu recorte programado está pronto.",
        f"Período: últimas {hours} horas | {_filter_label(terms, risk)}",
        f"Notícias encontradas: {stats['total']} | Risco crítico: {stats['por_risco'].get('10', 0)}",
        "",
    ]
    for index, item in enumerate(stats["principais"], 1):
        lines.extend([
            f"{index}. {item['titulo']}",
            f"{item['veiculo']} | {_date(item['publicada_em'])} | Risco {item['risco']}",
            item["url"],
            "",
        ])
    if not stats["principais"]:
        lines.append("Nenhuma notícia correspondeu aos filtros deste envio.")
    return "\n".join(lines)


@contextmanager
def _smtp_session():
    cfg = settings()
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if cfg.smtp_user:
            smtp.login(cfg.smtp_user, cfg.smtp_password)
        yield smtp


def _send(message: EmailMessage, recipients: list[str]) -> None:
    with _smtp_session() as smtp:
        smtp.send_message(message, to_addrs=recipients)


def _report_message(
    db,
    recipients: list[str],
    terms: list[str] | None,
    risk: int | None,
    recipient_name: str | None,
    hours: int,
    stats: dict | None = None,
) -> EmailMessage:
    data = stats if stats is not None else report_data(db, terms, risk, hours)
    message = EmailMessage()
    message["Subject"] = "Radar MCS | seu resumo de notícias"
    message["From"] = settings().report_from
    message["To"] = ", ".join(recipients)
    message.set_content(render_text_report(db, terms, risk, recipient_name, hours, data))
    message.add_alternative(render_report(db, terms, risk, recipient_name, hours, data), subtype="html")
    return message


def send_report(
    db,
    recipients: list[str] | None = None,
    terms: list[str] | None = None,
    risk: int | None = None,
    recipient_name: str | None = None,
    hours: int = 72,
) -> dict:
    cfg = settings()
    recipients = recipients or parse_recipients(cfg.report_to)
    if not all([cfg.smtp_host, recipients, cfg.report_from]):
        return {"enviado": False, "motivo": "SMTP ou destinatário não configurado"}
    message = _report_message(db, recipients, terms, risk, recipient_name, hours)
    _send(message, recipients)
    return {"enviado": True, "destinatarios": len(recipients), "noticias_no_email": EMAIL_NEWS_LIMIT}


def daily_report_accounts(db) -> list[dict]:
    """Carrega contas e palavras-chave em uma consulta, sem uma busca por usuário."""
    rows = db.execute(
        select(
            DashboardUser.id,
            DashboardUser.display_name,
            DashboardUser.email,
            UserKeyword.keyword,
        )
        .outerjoin(UserKeyword, UserKeyword.user_id == DashboardUser.id)
        .where(
            DashboardUser.active.is_(True),
            DashboardUser.email_verified.is_(True),
            DashboardUser.email.is_not(None),
        )
        .order_by(DashboardUser.id, UserKeyword.keyword)
    ).all()
    accounts: dict[int, dict] = {}
    for row in rows:
        account = accounts.setdefault(row.id, {
            "id": row.id,
            "display_name": row.display_name,
            "email": (row.email or "").strip().lower(),
            "keywords": [],
        })
        if row.keyword:
            account["keywords"].append(row.keyword)
    return list(accounts.values())


def send_daily_user_reports(db, hours: int = 72) -> dict:
    """Envia um boletim individual por conta usando uma única sessão SMTP."""
    cfg = settings()
    accounts = daily_report_accounts(db)
    eligible = [account for account in accounts if account["email"] and account["keywords"]]
    skipped = len(accounts) - len(eligible)
    if not cfg.smtp_host or not cfg.report_from:
        return {
            "enviado": False,
            "contas_elegiveis": len(eligible),
            "enviados": 0,
            "ignorados_sem_palavras": skipped,
            "falhas": len(eligible),
            "motivo": "SMTP não configurado",
        }
    if not eligible:
        return {
            "enviado": False,
            "contas_elegiveis": 0,
            "enviados": 0,
            "ignorados_sem_palavras": skipped,
            "falhas": 0,
            "motivo": "Nenhuma conta verificada com e-mail e palavras-chave",
        }

    stats_cache: dict[tuple[str, ...], dict] = {}
    prepared: list[tuple[list[str], EmailMessage]] = []
    preparation_failures = 0
    for account in eligible:
        terms = account["keywords"]
        cache_key = tuple(term.casefold() for term in terms)
        try:
            data = stats_cache.get(cache_key)
            if data is None:
                data = report_data(db, terms=terms, hours=hours)
                stats_cache[cache_key] = data
            recipients = [account["email"]]
            prepared.append((recipients, _report_message(
                db,
                recipients,
                terms,
                None,
                account["display_name"],
                hours,
                data,
            )))
        except Exception:
            preparation_failures += 1

    sent = 0
    delivery_failures = 0
    try:
        with _smtp_session() as smtp:
            for recipients, message in prepared:
                try:
                    smtp.send_message(message, to_addrs=recipients)
                    sent += 1
                except (OSError, smtplib.SMTPException):
                    delivery_failures += 1
    except (OSError, smtplib.SMTPException) as exc:
        return {
            "enviado": False,
            "contas_elegiveis": len(eligible),
            "enviados": 0,
            "ignorados_sem_palavras": skipped,
            "falhas": len(prepared) + preparation_failures,
            "motivo": f"Falha na conexão SMTP: {type(exc).__name__}",
        }

    failures = preparation_failures + delivery_failures
    return {
        "enviado": sent > 0,
        "contas_elegiveis": len(eligible),
        "enviados": sent,
        "ignorados_sem_palavras": skipped,
        "falhas": failures,
        "consultas_de_conteudo": len(stats_cache),
    }
