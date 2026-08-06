from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_user
from app.classifier import normalize
from app.dashboard_service import OverviewOptions, clear_dashboard_cache, filters, normalized_options, overview
from app.database import get_db
from app.models import (
    DashboardUser, EmailSchedule, McsAlert, UserKeyword, UserMcsAlertRead,
)


LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
KEYWORD_SPLIT = re.compile(r"[\r\n,;:.\"'“”‘’]+")


class KeywordRequest(BaseModel):
    keyword: str | None = None


class BatchRequest(BaseModel):
    text: str | None = None
    ids: list[int] | None = None


class ScheduleRequest(BaseModel):
    scheduledAt: datetime | None = None
    risk: int | None = None
    keywords: list[str] | None = None
    recipientEmail: str | None = None


class WhatsappReportRequest(BaseModel):
    risk: int | None = None
    keywords: list[str] | None = None


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(
    days: int = 7,
    keyword: list[str] | None = Query(None),
    source: list[str] | None = Query(None),
    section: list[str] | None = Query(None),
    risk: list[int] | None = Query(None),
    tone: list[str] | None = Query(None),
    query: str | None = None,
    location: list[str] | None = Query(None),
    includeAll: bool = False,
    page: int = 1,
    pageSize: int = 100,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    options = normalized_options(
        days, keyword, source, section, risk, tone, query, location,
        includeAll, page, pageSize,
    )
    return overview(db, user.id, options)


@router.get("/filters")
def dashboard_filters(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    return filters(db, user.id)


def _parse_keywords(value: str | None) -> tuple[list[str], int]:
    if not value or not value.strip():
        return [], 0
    unique: dict[str, str] = {}
    received = 0
    for part in KEYWORD_SPLIT.split(value):
        term = re.sub(r"\s+", " ", part).strip()
        if not 2 <= len(term) <= 255:
            continue
        received += 1
        unique.setdefault(normalize(term), term)
    return list(unique.values()), received


def _insert_keywords(db: Session, user_id: int, terms: list[str]) -> int:
    existing = {
        normalize(value)
        for value in db.scalars(select(UserKeyword.keyword).where(UserKeyword.user_id == user_id))
    }
    added = 0
    for term in terms:
        if normalize(term) in existing:
            continue
        db.add(UserKeyword(user_id=user_id, keyword=term))
        existing.add(normalize(term))
        added += 1
    try:
        db.commit()
    except IntegrityError:
        # A unique constraint remains the final guard if two requests race.
        db.rollback()
        added = 0
    if added:
        clear_dashboard_cache()
    return added


@router.get("/keywords")
def list_keywords(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(UserKeyword).where(UserKeyword.user_id == user.id).order_by(UserKeyword.keyword)
    ).all()
    return [{"id": row.id, "keyword": row.keyword} for row in rows]


@router.post("/keywords")
def add_keyword(body: KeywordRequest, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    terms, _ = _parse_keywords(body.keyword)
    if len(terms) != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Digite uma palavra-chave ou use a inclusão em lote")
    _insert_keywords(db, user.id, terms)
    row = db.scalar(
        select(UserKeyword).where(UserKeyword.user_id == user.id, UserKeyword.keyword == terms[0])
    )
    if row is None:
        # MariaDB normally compares this unique text case-insensitively.
        row = db.scalar(select(UserKeyword).where(UserKeyword.user_id == user.id))
    return {"id": row.id, "keyword": row.keyword}


@router.post("/keywords/batch")
def add_keyword_batch(body: BatchRequest, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    terms, received = _parse_keywords(body.text)
    if not terms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma palavra-chave válida foi encontrada")
    added = _insert_keywords(db, user.id, terms)
    return {"received": received, "added": added, "ignored": received - added}


@router.delete("/keywords/{keyword_id}")
def remove_keyword(keyword_id: int, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    changed = db.execute(
        delete(UserKeyword).where(UserKeyword.id == keyword_id, UserKeyword.user_id == user.id)
    ).rowcount
    db.commit()
    if not changed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Palavra-chave não encontrada")
    clear_dashboard_cache()
    return {"deleted": True}


@router.post("/keywords/delete-batch")
def remove_keyword_batch(body: BatchRequest, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(value for value in body.ids or [] if value is not None))[:500]
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione ao menos uma palavra-chave")
    removed = db.execute(
        delete(UserKeyword).where(UserKeyword.user_id == user.id, UserKeyword.id.in_(ids))
    ).rowcount
    db.commit()
    if removed:
        clear_dashboard_cache()
    return {"removed": removed}


def _json_list(value: str | None) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _selected_user_keywords(db: Session, user_id: int, requested: list[str] | None) -> list[str]:
    available = list(db.scalars(
        select(UserKeyword.keyword).where(UserKeyword.user_id == user_id).order_by(UserKeyword.keyword)
    ))
    if not requested:
        return available
    requested_normalized = {normalize(term) for term in requested if term and term.strip()}
    return [term for term in available if normalize(term) in requested_normalized]


@router.get("/alerts")
def alerts(
    limit: int = 20,
    beforeId: int | None = None,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    bounded = max(1, min(limit, 50))
    cutoff = datetime.now() - timedelta(days=90)
    statement = (
        select(McsAlert, UserMcsAlertRead.read_at)
        .outerjoin(
            UserMcsAlertRead,
            (UserMcsAlertRead.alert_id == McsAlert.id) & (UserMcsAlertRead.user_id == user.id),
        )
        .where(McsAlert.detected_at >= cutoff)
        .order_by(McsAlert.id.desc())
        .limit(bounded + 1)
    )
    if beforeId is not None:
        statement = statement.where(McsAlert.id < beforeId)
    rows = db.execute(statement).all()
    has_more = len(rows) > bounded
    rows = rows[:bounded]
    account_created = db.scalar(select(DashboardUser.created_at).where(DashboardUser.id == user.id))
    items = []
    for alert, read_at in rows:
        is_read = read_at is not None or (account_created is not None and alert.detected_at < account_created)
        item = {
            "id": alert.id, "title": alert.title, "url": alert.url, "source": alert.source,
            "detectedAt": alert.detected_at,
            "matchedTerms": _json_list(alert.matched_terms_json),
            "risk": alert.risk_score, "impact": alert.impact_score,
            "read": is_read,
        }
        if alert.published_at is not None:
            item["publishedAt"] = alert.published_at
        if alert.match_excerpt is not None:
            item["excerpt"] = alert.match_excerpt
        if read_at is not None:
            item["readAt"] = read_at
        items.append(item)
    return {
        "items": items,
        "unreadCount": _unread_count(db, user.id),
        "nextCursor": items[-1]["id"] if has_more and items else None,
    }


def _unread_count(db: Session, user_id: int) -> int:
    cutoff = datetime.now() - timedelta(days=90)
    created_at = db.scalar(select(DashboardUser.created_at).where(DashboardUser.id == user_id))
    if created_at is None:
        return 0
    return int(db.scalar(
        select(func.count()).select_from(McsAlert)
        .outerjoin(
            UserMcsAlertRead,
            (UserMcsAlertRead.alert_id == McsAlert.id) & (UserMcsAlertRead.user_id == user_id),
        )
        .where(
            UserMcsAlertRead.alert_id.is_(None),
            McsAlert.detected_at >= created_at,
            McsAlert.detected_at >= cutoff,
        )
    ) or 0)


@router.get("/alerts/unread-count")
def unread_count(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    return {"unreadCount": _unread_count(db, user.id)}


@router.put("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    cutoff = datetime.now() - timedelta(days=90)
    alert = db.scalar(select(McsAlert).where(McsAlert.id == alert_id, McsAlert.detected_at >= cutoff))
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta não encontrado")
    exists = db.get(UserMcsAlertRead, (user.id, alert_id))
    if exists is None:
        db.add(UserMcsAlertRead(user_id=user.id, alert_id=alert_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"unreadCount": _unread_count(db, user.id)}


@router.put("/alerts/read-all")
def mark_all_alerts_read(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    cutoff = datetime.now() - timedelta(days=90)
    created_at = db.scalar(select(DashboardUser.created_at).where(DashboardUser.id == user.id))
    unread_ids = db.scalars(
        select(McsAlert.id)
        .outerjoin(
            UserMcsAlertRead,
            (UserMcsAlertRead.alert_id == McsAlert.id) & (UserMcsAlertRead.user_id == user.id),
        )
        .where(
            UserMcsAlertRead.alert_id.is_(None),
            McsAlert.detected_at >= created_at,
            McsAlert.detected_at >= cutoff,
        )
    ).all()
    db.add_all(UserMcsAlertRead(user_id=user.id, alert_id=alert_id) for alert_id in unread_ids)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"unreadCount": _unread_count(db, user.id)}


@router.get("/email-schedules")
def list_schedules(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(EmailSchedule).where(EmailSchedule.user_id == user.id).order_by(EmailSchedule.scheduled_at)
    ).all()
    result = []
    for row in rows:
        item = {
            "id": row.id, "scheduledAt": row.scheduled_at,
            "keywords": _json_list(row.keywords_json),
            "recipientEmail": row.recipient_email or user.email,
            "status": row.status, "createdAt": row.created_at,
        }
        if row.risk_score is not None:
            item["risk"] = row.risk_score
        if row.prepared_at is not None:
            item["preparedAt"] = row.prepared_at
        if row.sent_at is not None:
            item["sentAt"] = row.sent_at
        if row.last_error is not None:
            item["lastError"] = row.last_error
        result.append(item)
    return result


@router.post("/whatsapp-report")
def whatsapp_report(
    body: WhatsappReportRequest,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    allowed = db.scalar(
        select(DashboardUser.can_send_whatsapp).where(
            DashboardUser.id == user.id,
            DashboardUser.active.is_(True),
        )
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sua conta não possui permissão para compartilhar relatórios no WhatsApp")
    if body.risk is not None and body.risk not in (0, 5, 10):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione um risco válido")
    selected = _selected_user_keywords(db, user.id, body.keywords)
    if not selected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione ao menos uma palavra-chave")
    return overview(db, user.id, OverviewOptions(
        days=1,
        keywords=tuple(selected),
        risks=(body.risk,) if body.risk is not None else (),
        page_size=12,
        prioritize_articles=True,
    ))


@router.post("/email-schedules")
def create_schedule(
    body: ScheduleRequest,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cadastre um e-mail na conta antes de programar o envio")
    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    scheduled_at = body.scheduledAt
    if scheduled_at and scheduled_at.tzinfo:
        scheduled_at = scheduled_at.astimezone(LOCAL_TZ).replace(tzinfo=None)
    if scheduled_at is None or scheduled_at <= now + timedelta(minutes=2):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha um horário com pelo menos 2 minutos de antecedência")
    if body.risk is not None and body.risk not in (0, 5, 10):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione um risco válido")
    requested = (body.recipientEmail or "").strip().lower()
    account_email = user.email.strip().lower()
    if requested and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", requested):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe um e-mail de destino válido")
    external = bool(requested and requested != account_email)
    if external:
        allowed = db.scalar(
            select(DashboardUser.can_send_external_email).where(
                DashboardUser.id == user.id, DashboardUser.active.is_(True)
            )
        )
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sua conta não possui permissão para enviar a outro e-mail")
    pending = db.scalar(
        select(func.count()).select_from(EmailSchedule).where(
            EmailSchedule.user_id == user.id,
            EmailSchedule.status.in_(["PENDING", "PREPARING"]),
        )
    ) or 0
    if pending >= 2:
        raise HTTPException(status.HTTP_409_CONFLICT, "Você já possui dois envios programados")
    selected = _selected_user_keywords(db, user.id, body.keywords)
    if not selected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione ao menos uma palavra-chave")
    schedule = EmailSchedule(
        user_id=user.id,
        scheduled_at=scheduled_at,
        risk_score=body.risk,
        keywords_json=json.dumps(selected, ensure_ascii=False),
        recipient_email=requested if external else None,
        status="PENDING",
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {"id": schedule.id}


@router.delete("/email-schedules/{schedule_id}")
def cancel_schedule(schedule_id: int, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    removed = db.execute(
        delete(EmailSchedule).where(
            EmailSchedule.id == schedule_id,
            EmailSchedule.user_id == user.id,
            EmailSchedule.status.in_(["PENDING", "FAILED"]),
        )
    ).rowcount
    db.commit()
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agendamento não encontrado ou já enviado")
    return {"deleted": True}
