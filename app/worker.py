import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from app.database import Base, engine, SessionLocal
from app.services import collect
from app.reports import send_report

logging.basicConfig(level=logging.INFO)
def job():
    with SessionLocal() as db: logging.info("Coleta concluida: %s", collect(db))

def report_job():
    with SessionLocal() as db: logging.info("Relatório: %s", send_report(db))

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(job, "cron", hour=4, minute=30, id="coleta_diaria", replace_existing=True)
    scheduler.add_job(report_job, "cron", hour=7, minute=0, id="relatorio_diario", replace_existing=True)
    scheduler.start()
