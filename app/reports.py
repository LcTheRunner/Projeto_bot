import smtplib
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from zoneinfo import ZoneInfo

from app.config import settings
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
) -> str:
    stats = report_data(db, terms, risk, hours)
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
) -> str:
    stats = report_data(db, terms, risk, hours)
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


def _send(message: EmailMessage, recipients: list[str]) -> None:
    cfg = settings()
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
        smtp.starttls()
        if cfg.smtp_user:
            smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(message, to_addrs=recipients)


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
    message = EmailMessage()
    message["Subject"] = "Radar MCS | seu resumo de notícias"
    message["From"], message["To"] = cfg.report_from, ", ".join(recipients)
    message.set_content(render_text_report(db, terms, risk, recipient_name, hours))
    message.add_alternative(render_report(db, terms, risk, recipient_name, hours), subtype="html")
    _send(message, recipients)
    return {"enviado": True, "destinatarios": len(recipients), "noticias_no_email": EMAIL_NEWS_LIMIT}
