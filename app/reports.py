import smtplib
from email.message import EmailMessage
from html import escape
from app.config import settings
from app.services import weekly_stats

def render_report(db) -> str:
    stats = weekly_stats(db)
    rows = lambda data: "".join(f"<li>{escape(str(k))}: {v}</li>" for k, v in data.items()) or "<li>Sem dados</li>"
    return f"""<h1>Monitoramento midiático</h1><p>Total nos últimos 7 dias: <strong>{stats['total']}</strong></p><h2>Risco</h2><ul>{rows(stats['por_risco'])}</ul><h2>Veículos</h2><ul>{rows(stats['por_veiculo'])}</ul><h2>Editorias</h2><ul>{rows(stats['por_editoria'])}</ul><h2>Jornalistas</h2><ul>{rows(stats['por_jornalista'])}</ul>"""

def send_report(db) -> dict:
    cfg = settings()
    if not all([cfg.smtp_host, cfg.report_to, cfg.report_from]): return {"enviado": False, "motivo": "SMTP não configurado"}
    message = EmailMessage()
    message["Subject"] = "Relatório diário de impacto midiático"
    message["From"], message["To"] = cfg.report_from, cfg.report_to
    message.set_content("Seu cliente de e-mail precisa aceitar HTML.")
    message.add_alternative(render_report(db), subtype="html")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
        smtp.starttls()
        if cfg.smtp_user: smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(message)
    return {"enviado": True}
