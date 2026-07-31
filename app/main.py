import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from app.database import Base, engine, get_db
from app.models import Article
from app.services import backfill_journalists, backfill_mcs_alerts, collect, recent_cutoff, recent_stats
from app.reports import send_report

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        backfill_mcs_alerts(db)
    yield

app = FastAPI(title="Monitor de Impacto Midiático", version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/coletas")
def run_collection(db: Session = Depends(get_db)): return collect(db)

@app.get("/noticias")
def articles(risco: int | None = None, limite: int = Query(50, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Article)
        .options(joinedload(Article.classification))
        .where(Article.published_at >= recent_cutoff())
        .order_by(Article.published_at.desc())
        .limit(limite)
    ).unique().all()
    if risco is not None: rows = [a for a in rows if a.classification.risk_score == risco]
    return [{"id": a.id, "titulo": a.title, "url": a.url, "veiculo": a.source, "editoria": a.section, "jornalista": a.journalist, "telefone_profissional_publico": a.journalist_phone, "publicada_em": a.published_at, "risco": a.classification.risk_score, "tom": a.classification.tone, "impacto": a.classification.impact_score, "palavras": json.loads(a.classification.matched_keywords), "evidencias": json.loads(a.classification.evidence)} for a in rows]

@app.get("/estatisticas/semana")
@app.get("/estatisticas/72h")
def stats(termo: str | None = None, db: Session = Depends(get_db)): return recent_stats(db, termo)

@app.post("/relatorios/enviar")
def report(db: Session = Depends(get_db)): return send_report(db)

@app.post("/jornalistas/atualizar")
def update_journalists(limite: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return backfill_journalists(db, limite)
