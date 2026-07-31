import logging
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.database import Base, engine, SessionLocal
from app.services import collect, collect_mcs_alerts
from app.reports import send_report

logging.basicConfig(level=logging.INFO)
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

def job():
    with SessionLocal() as db: logging.info("Coleta concluida: %s", collect(db))

def report_job():
    with SessionLocal() as db: logging.info("Relatório: %s", send_report(db))

def mcs_alert_job():
    with SessionLocal() as db: logging.info("Alertas MCS: %s", collect_mcs_alerts(db))

def scheduled_email_job():
    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    prepare_until = now + timedelta(minutes=20)
    with SessionLocal() as db:
        try:
            recovered = db.execute(text("""
                UPDATE email_schedules
                SET status = 'FAILED',
                    last_error = 'O worker foi interrompido durante o envio. Cancele este registro e programe novamente'
                WHERE status = 'PREPARING' AND scheduled_at < :stale_before
            """), {"stale_before": now - timedelta(minutes=30)})
            if recovered.rowcount:
                db.commit()
                logging.warning("%s envio(s) interrompido(s) foram liberados", recovered.rowcount)

            schedules_to_prepare = db.execute(text("""
                SELECT id, keywords_json FROM email_schedules
                WHERE status = 'PENDING' AND prepared_at IS NULL
                  AND scheduled_at <= :prepare_until
            """), {"prepare_until": prepare_until}).mappings().all()
            if schedules_to_prepare:
                scheduled_keywords = []
                for item in schedules_to_prepare:
                    try:
                        scheduled_keywords.extend(json.loads(item["keywords_json"] or "[]"))
                    except (TypeError, json.JSONDecodeError):
                        logging.warning("Palavras invalidas no agendamento %s", item["id"])
                logging.info("Preparando coleta para %s envio(s) programado(s)", len(schedules_to_prepare))
                result = collect(db, extra_keywords=scheduled_keywords)
                db.execute(text("""
                    UPDATE email_schedules SET prepared_at = :now
                    WHERE status = 'PENDING' AND prepared_at IS NULL
                      AND scheduled_at <= :prepare_until
                """), {"now": now, "prepare_until": prepare_until})
                db.commit()
                logging.info("Coleta previa concluida: %s", result)

            due = db.execute(text("""
                SELECT s.id, s.risk_score, s.keywords_json, u.username, u.email
                FROM email_schedules s
                JOIN dashboard_users u ON u.id = s.user_id
                WHERE s.status = 'PENDING' AND s.scheduled_at <= :now
                  AND u.active = TRUE AND u.email_verified = TRUE
                ORDER BY s.scheduled_at
            """), {"now": now}).mappings().all()
        except SQLAlchemyError as exc:
            db.rollback()
            logging.warning("Agenda de e-mail ainda indisponivel: %s", type(exc).__name__)
            return

        for schedule in due:
            schedule_id = schedule["id"]
            try:
                claimed = db.execute(text("""
                    UPDATE email_schedules SET status = 'PREPARING', last_error = NULL
                    WHERE id = :id AND status = 'PENDING'
                """), {"id": schedule_id})
                db.commit()
                if claimed.rowcount != 1:
                    continue
                keywords = json.loads(schedule["keywords_json"] or "[]")
                result = send_report(
                    db,
                    recipients=[schedule["email"]],
                    terms=keywords,
                    risk=schedule["risk_score"],
                    recipient_name=schedule["username"],
                    hours=24,
                )
                if not result.get("enviado"):
                    raise RuntimeError(result.get("motivo", "Falha no envio"))
                db.execute(text("""
                    UPDATE email_schedules
                    SET status = 'SENT', sent_at = :now, last_error = NULL
                    WHERE id = :id
                """), {"id": schedule_id, "now": datetime.now(LOCAL_TZ).replace(tzinfo=None)})
                db.commit()
                logging.info("Envio programado %s concluido", schedule_id)
            except Exception as exc:
                db.rollback()
                db.execute(text("""
                    UPDATE email_schedules SET status = 'FAILED', last_error = :error
                    WHERE id = :id
                """), {"id": schedule_id, "error": str(exc)[:500]})
                db.commit()
                logging.exception("Falha no envio programado %s", schedule_id)

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(job, "cron", hour=4, minute=30, id="coleta_diaria", replace_existing=True)
    scheduler.add_job(report_job, "cron", hour=7, minute=0, id="relatorio_diario", replace_existing=True)
    scheduler.add_job(
        mcs_alert_job,
        "interval",
        minutes=15,
        id="alertas_mcs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(LOCAL_TZ),
    )
    scheduler.add_job(
        scheduled_email_job,
        "interval",
        minutes=1,
        id="envios_programados",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
