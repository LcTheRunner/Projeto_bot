import smtplib
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from zoneinfo import ZoneInfo
from app.config import settings
from app.services import recent_stats

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
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
SCOPE_LABELS = {
    "marica": "Maricá",
    "estado_rj": "Estado do RJ",
    "nacional": "Nacional",
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

def _summary_rows(data: dict, labels: bool = False, limit: int | None = None) -> str:
    entries = list(data.items())[:limit]
    if not entries:
        return '<tr><td style="padding:10px;color:#64748b">Sem dados</td><td></td></tr>'
    return "".join(
        '<tr>'
        f'<td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;color:#334155">{escape(_label(str(key)) if labels else str(key))}</td>'
        f'<td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;color:#0f172a">{value}</td>'
        '</tr>'
        for key, value in entries
    )

def _highlight_card(item: dict) -> str:
    colors = {"crítica": ("#fee2e2", "#b91c1c"), "alta": ("#ffedd5", "#c2410c"), "relevante": ("#dbeafe", "#1d4ed8")}
    background, foreground = colors[item["prioridade"]]
    keywords = ", ".join(item["palavras"][:6]) or "tema monitorado"
    return f"""
    <tr><td style="padding:0 0 14px">
      <table role="presentation" width="100%" style="border:1px solid #e2e8f0;border-radius:10px;background:#ffffff">
        <tr><td style="padding:18px">
          <span style="display:inline-block;padding:4px 9px;border-radius:999px;background:#dcfce7;color:#166534;font-size:11px;font-weight:700;text-transform:uppercase">{escape(SCOPE_LABELS[item['abrangencia']])}</span>
          <span style="display:inline-block;margin-left:5px;padding:4px 9px;border-radius:999px;background:{background};color:{foreground};font-size:11px;font-weight:700;text-transform:uppercase">Prioridade {escape(item['prioridade'])}</span>
          <h3 style="margin:10px 0 7px;font-size:17px;line-height:1.35;color:#0f172a">
            <a href="{escape(item['url'], quote=True)}" style="color:#0f172a;text-decoration:none">{escape(item['titulo'])}</a>
          </h3>
          <p style="margin:0 0 6px;color:#475569;font-size:13px">{escape(item['veiculo'])} · {escape(_label(item['editoria']))} · {_date(item['publicada_em'])}</p>
          <p style="margin:0 0 14px;color:#64748b;font-size:12px">Risco {item['risco']} · Impacto {item['impacto']} · {escape(keywords)}</p>
          <a href="{escape(item['url'], quote=True)}" style="display:inline-block;padding:9px 14px;border-radius:7px;background:#1d4ed8;color:#ffffff;text-decoration:none;font-size:13px;font-weight:700">Abrir notícia</a>
        </td></tr>
      </table>
    </td></tr>"""

def render_report(db) -> str:
    stats = recent_stats(db)
    highlights = "".join(_highlight_card(item) for item in stats["principais"])
    if not highlights:
        highlights = '<tr><td style="padding:18px;background:#fff;border-radius:10px;color:#64748b">Nenhuma notícia relevante nas últimas 72 horas.</td></tr>'
    generated_at = datetime.now(LOCAL_TZ).strftime("%d/%m/%Y às %H:%M")
    return f"""<!doctype html>
<html><body style="margin:0;background:#f1f5f9;font-family:Arial,sans-serif;color:#0f172a">
<div style="display:none;max-height:0;overflow:hidden">Resumo das notícias monitoradas nas últimas 72 horas.</div>
<table role="presentation" width="100%" style="background:#f1f5f9"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:720px">
  <tr><td style="padding:28px;border-radius:14px 14px 0 0;background:#0f172a;color:#fff">
    <p style="margin:0 0 7px;color:#93c5fd;font-size:12px;font-weight:700;text-transform:uppercase">Monitoramento midiático</p>
    <h1 style="margin:0;font-size:28px">Notícias das últimas 72 horas</h1>
    <p style="margin:9px 0 0;color:#cbd5e1;font-size:14px">Atualizado em {generated_at}</p>
  </td></tr>
  <tr><td style="padding:22px;background:#ffffff">
    <table role="presentation" width="100%"><tr>
      <td width="50%" style="padding:16px;border-radius:10px;background:#eff6ff"><div style="font-size:28px;font-weight:800;color:#1d4ed8">{stats['total']}</div><div style="font-size:13px;color:#475569">notícias relevantes</div></td>
      <td width="4%"></td>
      <td width="46%" style="padding:16px;border-radius:10px;background:#fef2f2"><div style="font-size:28px;font-weight:800;color:#b91c1c">{stats['por_risco'].get('10', 0)}</div><div style="font-size:13px;color:#475569">notícias de risco crítico</div></td>
    </tr></table>
    <h2 style="margin:26px 0 12px;font-size:19px">Distribuição do monitoramento</h2>
    <table role="presentation" width="100%"><tr>
      <td width="52%" valign="top"><table role="presentation" width="100%">{_summary_rows(stats['por_editoria'], labels=True)}</table></td>
      <td width="4%"></td>
      <td width="44%" valign="top"><table role="presentation" width="100%">{_summary_rows(stats['por_veiculo'], limit=7)}</table></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:24px 22px;background:#e2e8f0">
    <h2 style="margin:0 0 5px;font-size:21px">Notícias mais importantes</h2>
    <p style="margin:0 0 16px;color:#475569;font-size:13px">Maricá e Estado do Rio de Janeiro em primeiro lugar; depois risco, impacto e recência.</p>
    <table role="presentation" width="100%">{highlights}</table>
  </td></tr>
  <tr><td style="padding:18px 24px;border-radius:0 0 14px 14px;background:#0f172a;color:#94a3b8;font-size:12px;text-align:center">Relatório automático · Janela móvel de 72 horas</td></tr>
</table></td></tr></table></body></html>"""

def render_text_report(db) -> str:
    stats = recent_stats(db)
    lines = [
        "MONITORAMENTO MIDIÁTICO — ÚLTIMAS 72 HORAS",
        f"Total de notícias relevantes: {stats['total']}",
        f"Risco crítico: {stats['por_risco'].get('10', 0)}",
        "",
        "NOTÍCIAS MAIS IMPORTANTES",
    ]
    for index, item in enumerate(stats["principais"], 1):
        lines.extend([
            f"{index}. {item['titulo']}",
            f"{item['veiculo']} | {_label(item['editoria'])} | {_date(item['publicada_em'])}",
            f"Abrangência: {SCOPE_LABELS[item['abrangencia']]} | Prioridade: {item['prioridade']} | Risco: {item['risco']} | Impacto: {item['impacto']}",
            item["url"],
            "",
        ])
    if not stats["principais"]:
        lines.append("Nenhuma notícia relevante nas últimas 72 horas.")
    return "\n".join(lines)

def send_report(db, recipients: list[str] | None = None) -> dict:
    cfg = settings()
    recipients = recipients or parse_recipients(cfg.report_to)
    if not all([cfg.smtp_host, recipients, cfg.report_from]): return {"enviado": False, "motivo": "SMTP ou destinatário não configurado"}
    message = EmailMessage()
    message["Subject"] = "Monitoramento RJ e Maricá: notícias das últimas 72 horas"
    message["From"], message["To"] = cfg.report_from, ", ".join(recipients)
    message.set_content(render_text_report(db))
    message.add_alternative(render_report(db), subtype="html")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
        smtp.starttls()
        if cfg.smtp_user: smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(message, to_addrs=recipients)
    return {"enviado": True, "destinatarios": len(recipients)}
