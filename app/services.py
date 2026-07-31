import json
import re
import hashlib
import html
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.classifier import classify, is_relevant, normalize, result_json
from app.collectors import rss_items, google_news_items, google_items, instagram_items, enrich
from app.config import yaml_config
from app.models import Article, Classification, McsAlert

NEWS_WINDOW_HOURS = 72
ALERT_HISTORY_DAYS = 90
GLOBAL_ALERT_TERMS = ["Movimento Cultural Social", "Instituto Carioca"]
GLOBAL_ALERT_QUERIES = [
    '"Movimento Cultural Social"',
    '"Instituto Carioca"',
]
_INSTITUTIONAL_ALERT_PATTERNS = (
    ("Movimento Cultural Social", re.compile(r"(?<!\w)movimento\s+cultural\s+social(?!\w)", re.IGNORECASE)),
    ("Instituto Carioca", re.compile(r"(?<!\w)instituto\s+carioca(?!\w)", re.IGNORECASE)),
)
RJ_TERMS = [
    "rio de janeiro",
    "estado do rio",
    "governo do rio",
    "assembleia legislativa do rio",
    "alerj",
    "niterói",
    "são gonçalo",
    "duque de caxias",
    "nova iguaçu",
    "belford roxo",
    "são joão de meriti",
    "petrópolis",
    "teresópolis",
    "nova friburgo",
    "cabo frio",
    "búzios",
    "angra dos reis",
    "volta redonda",
    "barra mansa",
    "campos dos goytacazes",
    "macaé",
]

def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

def recent_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=NEWS_WINDOW_HOURS)

def is_recent(value: datetime | None) -> bool:
    return value is None or _aware(value) >= recent_cutoff()

def _alert_plain_text(title: str, body: str) -> str:
    value = html.unescape(f"{title or ''}. {body or ''}")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\S+@\S+\b", " ", value)
    value = re.sub(
        r"(?<![@\w])(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<!\w)[@#][\w.-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def mcs_alert_terms(title: str, body: str) -> list[str]:
    text = normalize(_alert_plain_text(title, body))
    return [label for label, pattern in _INSTITUTIONAL_ALERT_PATTERNS if pattern.search(text)]

def _mcs_alert_excerpt(title: str, body: str) -> str:
    text = _alert_plain_text(title, body)
    matches = [
        match
        for _, pattern in _INSTITUTIONAL_ALERT_PATTERNS
        if (match := pattern.search(text))
    ]
    if not matches:
        return text[:520]
    match = min(matches, key=lambda item: item.start())
    start = max(0, match.start() - 150)
    end = min(len(text), match.end() + 260)
    prefix = "… " if start else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"[:600]

def _store_mcs_alert(
    db: Session,
    article: Article,
    classification: Classification,
    snapshot: dict | None = None,
) -> bool:
    snapshot = snapshot or {}
    title = str(snapshot.get("title") or article.title)
    body = str(snapshot.get("body") or article.body)
    url = str(snapshot.get("url") or article.url)
    source = str(snapshot.get("source") or article.source)
    published_at = snapshot.get("published_at") or article.published_at
    terms = mcs_alert_terms(title, body)
    if not terms:
        return False
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    values = {
        "article_id": article.id,
        "url_hash": url_hash,
        "title": title,
        "url": url,
        "source": source,
        "published_at": published_at,
        "matched_terms_json": json.dumps(terms, ensure_ascii=False),
        "match_excerpt": _mcs_alert_excerpt(title, body),
        "risk_score": classification.risk_score,
        "impact_score": classification.impact_score,
    }
    dialect = db.get_bind().dialect.name
    if dialect in {"mysql", "mariadb"}:
        statement = mysql_insert(McsAlert).values(**values).prefix_with("IGNORE")
        return db.execute(statement).rowcount == 1
    if dialect == "sqlite":
        statement = sqlite_insert(McsAlert).values(**values).on_conflict_do_nothing()
        return db.execute(statement).rowcount == 1
    try:
        with db.begin_nested():
            return db.execute(insert(McsAlert).values(**values)).rowcount == 1
    except IntegrityError:
        return False

def _deduplicate_items(items: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in items:
        url = item.get("url")
        if not url:
            continue
        previous = unique.get(url)
        if previous is None:
            unique[url] = item
            continue
        previous_priority = bool(previous.get("_global_alert_candidate"))
        current_priority = bool(item.get("_global_alert_candidate"))
        if current_priority and not previous_priority:
            preferred = item
        elif previous_priority and not current_priority:
            preferred = previous
        else:
            previous_body = str(previous.get("body") or "")
            current_body = str(item.get("body") or "")
            preferred = item if len(current_body) > len(previous_body) else previous
        merged = dict(preferred)
        merged["_global_alert_candidate"] = previous_priority or current_priority
        merged["_skip_enrich"] = bool(
            previous.get("_skip_enrich", False)
            and item.get("_skip_enrich", False)
        )
        unique[url] = merged
    return list(unique.values())

def _store_existing_candidate(
    db: Session,
    article: Article,
    item: dict,
    skip_enrich: bool,
    source_weight: float = 1.0,
) -> bool:
    url_hash = hashlib.sha256(article.url.encode("utf-8")).hexdigest()
    if db.scalar(select(McsAlert.id).where(McsAlert.url_hash == url_hash)):
        return False
    candidate = dict(item)
    if not skip_enrich:
        candidate = enrich(candidate)
    candidate["body"] = "\n\n".join(dict.fromkeys(filter(None, [
        article.title,
        article.body,
        candidate.get("body"),
    ])))
    if not mcs_alert_terms(str(candidate.get("title") or article.title), candidate["body"]):
        return False
    result = classify(
        str(candidate.get("title") or article.title),
        candidate["body"],
        source_weight=source_weight,
        extra_terms=GLOBAL_ALERT_TERMS,
    )
    classification = Classification(
        risk_score=result.risk_score,
        impact_score=result.impact_score,
    )
    created = _store_mcs_alert(db, article, classification, candidate)
    if created:
        db.commit()
    return created

def prune_mcs_alerts(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ALERT_HISTORY_DAYS)
    expired = db.scalars(select(McsAlert).where(McsAlert.detected_at < cutoff)).all()
    for alert in expired:
        db.delete(alert)
    removed = len(expired)
    changed = bool(expired)
    current = db.scalars(select(McsAlert).where(McsAlert.detected_at >= cutoff)).all()
    for alert in current:
        terms = mcs_alert_terms(alert.title, alert.match_excerpt or "")
        if not terms:
            db.delete(alert)
            removed += 1
            changed = True
            continue
        encoded = json.dumps(terms, ensure_ascii=False)
        if alert.matched_terms_json != encoded:
            alert.matched_terms_json = encoded
            changed = True
    if changed:
        db.commit()
    return removed

def backfill_mcs_alerts(db: Session) -> dict:
    removed = prune_mcs_alerts(db)
    rows = db.execute(
        select(Article, Classification)
        .join(Classification)
        .where(Article.published_at >= recent_cutoff())
        .order_by(Article.published_at, Article.id)
    ).all()
    created = sum(_store_mcs_alert(db, article, classification) for article, classification in rows)
    if created:
        db.commit()
    return {
        "analisadas": len(rows),
        "alertas_criados": created,
        "alertas_expirados": removed,
    }

def geographic_scope(article: Article) -> str:
    text = normalize(f"{article.title}. {article.body}. {article.source}")
    if re.search(r"(?<!\w)marica(?!\w)", text):
        return "marica"
    if re.search(r"(?<!\w)rj(?!\w)", text) or any(normalize(term) in text for term in RJ_TERMS):
        return "estado_rj"
    return "nacional"

def prune_expired(db: Session) -> int:
    expired = db.scalars(select(Article).where(Article.published_at < recent_cutoff())).all()
    for article in expired:
        db.delete(article)
    if expired:
        db.commit()
    return len(expired)

def save_item(
    db: Session,
    item: dict,
    user_keywords: list[str] | None = None,
    alert_only: bool = False,
) -> Article | None:
    if not item.get("url"): return None
    item = dict(item)
    relevance_terms = list(dict.fromkeys([*GLOBAL_ALERT_TERMS, *(user_keywords or [])]))
    source_weight = float(item.pop("_source_weight", 1.0))
    skip_enrich = bool(item.pop("_skip_enrich", False))
    global_alert_candidate = bool(item.pop("_global_alert_candidate", False))
    if not is_recent(item.get("published_at")): return None
    existing = db.scalar(select(Article).where(Article.url == item["url"]))
    if existing:
        if global_alert_candidate:
            _store_existing_candidate(db, existing, item, skip_enrich, source_weight)
        return None
    feed_matches_scope = (
        bool(mcs_alert_terms(item.get("title", ""), item.get("body", "")))
        if alert_only
        else is_relevant(item.get("title", ""), item.get("body", ""), relevance_terms)
    )
    if (
        not global_alert_candidate
        and not feed_matches_scope
    ):
        return None
    if not skip_enrich:
        item = enrich(item)
    result = classify(item["title"], item["body"], source_weight=source_weight, extra_terms=relevance_terms)
    if alert_only:
        if not mcs_alert_terms(item["title"], item["body"]): return None
    elif not is_relevant(item["title"], item["body"], relevance_terms):
        return None
    keywords, evidence = result_json(result)
    article = Article(**item, section=result.section)
    classification = Classification(
        risk_score=result.risk_score,
        tone=result.tone,
        impact_score=result.impact_score,
        matched_keywords=keywords,
        evidence=evidence,
    )
    article.classification = classification
    try:
        db.add(article)
        db.flush()
        _store_mcs_alert(db, article, classification)
        db.commit()
    except IntegrityError:
        # Outra coleta pode ter inserido a mesma URL entre a consulta e o flush.
        db.rollback()
        if global_alert_candidate:
            winner = db.scalar(select(Article).where(Article.url == item["url"]))
            if winner:
                _store_existing_candidate(db, winner, item, skip_enrich=True, source_weight=source_weight)
        return None
    db.refresh(article)
    return article

def collect(db: Session, extra_keywords: list[str] | None = None) -> dict:
    removed = prune_expired(db)
    removed_alerts = prune_mcs_alerts(db)
    sources = yaml_config("sources.yaml")
    user_keywords = _user_keywords(db)
    known = {normalize(value) for value in user_keywords}
    for value in extra_keywords or []:
        clean = str(value).strip()
        normalized = normalize(clean)
        if clean and normalized not in known:
            user_keywords.append(clean)
            known.add(normalized)
    collection_terms = list(dict.fromkeys([*GLOBAL_ALERT_TERMS, *user_keywords]))
    items = rss_items(global_alert_scan=True) + google_news_items(
        user_keywords,
        priority_queries=GLOBAL_ALERT_QUERIES,
    )
    if sources.get("google", {}).get("enabled", False):
        for query in sources.get("google", {}).get("queries", []): items += google_items(query)
    if sources.get("instagram", {}).get("enabled", False):
        for hashtag in yaml_config("keywords.yaml").get("hashtags_instagram", []): items += instagram_items(hashtag)
    unique = _deduplicate_items(items)
    recent = [item for item in unique if is_recent(item.get("published_at"))]
    relevant = [
        item for item in recent
        if item.get("_global_alert_candidate")
        or is_relevant(item.get("title", ""), item.get("body", ""), collection_terms)
    ]
    saved = sum(save_item(db, item, collection_terms) is not None for item in relevant)
    return {
        "encontrados": len(unique),
        "ultimas_72h": len(recent),
        "relevantes": len(relevant),
        "descartados": len(unique) - len(relevant),
        "novos": saved,
        "expirados_removidos": removed,
        "alertas_expirados": removed_alerts,
    }

def collect_mcs_alerts(db: Session) -> dict:
    removed = prune_mcs_alerts(db)
    items = rss_items() + google_news_items(
        priority_queries=GLOBAL_ALERT_QUERIES,
        priority_only=True,
    )
    unique = _deduplicate_items(items)
    recent = [item for item in unique if is_recent(item.get("published_at"))]
    relevant = [
        item for item in recent
        if item.get("_global_alert_candidate")
        or mcs_alert_terms(item.get("title", ""), item.get("body", ""))
    ]
    for item in relevant:
        item["_global_alert_candidate"] = True
        item.setdefault("_skip_enrich", False)
    alerts_before = db.scalar(select(func.count()).select_from(McsAlert)) or 0
    saved_articles = sum(
        save_item(db, item, GLOBAL_ALERT_TERMS, alert_only=True) is not None
        for item in relevant
    )
    alerts_after = db.scalar(select(func.count()).select_from(McsAlert)) or 0
    return {
        "encontrados": len(unique),
        "ultimas_72h": len(recent),
        "relevantes_alerta": len(relevant),
        "novos": max(0, alerts_after - alerts_before),
        "novas_noticias": saved_articles,
        "alertas_expirados": removed,
    }

def _user_keywords(db: Session) -> list[str]:
    try:
        rows = db.execute(text("SELECT DISTINCT keyword FROM user_keywords ORDER BY keyword")).scalars().all()
        return [str(value).strip() for value in rows if value and str(value).strip()]
    except Exception:
        db.rollback()
        return []

def recent_stats(
    db: Session,
    term: str | None = None,
    top_limit: int = 15,
    terms: list[str] | None = None,
    risk: int | None = None,
    hours: int = NEWS_WINDOW_HOURS,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(select(Article, Classification).join(Classification).where(Article.published_at >= since)).all()
    if term:
        terms = [term]
    if terms:
        needles = [normalize(value) for value in terms if value and value.strip()]
        rows = [
            row for row in rows
            if any(needle in normalize(f"{row.Article.title} {row.Article.body}") for needle in needles)
        ]
    if risk is not None:
        rows = [row for row in rows if row.Classification.risk_score == risk]
    def count(field):
        out = {}
        for a, _ in rows:
            key = getattr(a, field) or "nao_identificado"; out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items(), key=lambda x: -x[1]))
    risks = {}
    for _, c in rows: risks[str(c.risk_score)] = risks.get(str(c.risk_score), 0) + 1
    ordered = sorted(
        rows,
        key=lambda row: (
            row.Classification.risk_score,
            row.Classification.impact_score,
            _aware(row.Article.published_at),
        ),
        reverse=True,
    )
    # Brasil inteiro é o padrão; recortes regionais pertencem aos filtros da interface.
    selected = ordered[:top_limit]
    highlights = []
    for article, classification in selected[:top_limit]:
        if classification.risk_score >= 10:
            priority = "crítica"
        elif classification.risk_score >= 7 or classification.impact_score >= 8:
            priority = "alta"
        else:
            priority = "relevante"
        highlights.append({
            "titulo": article.title,
            "url": article.url,
            "veiculo": article.source,
            "jornalista": article.journalist,
            "editoria": article.section,
            "publicada_em": article.published_at,
            "risco": classification.risk_score,
            "impacto": classification.impact_score,
            "prioridade": priority,
            "abrangencia": geographic_scope(article),
            "palavras": json.loads(classification.matched_keywords),
        })
    return {
        "periodo_horas": hours,
        "termo": term,
        "total": len(rows),
        "por_veiculo": count("source"),
        "por_editoria": count("section"),
        "por_jornalista": count("journalist"),
        "por_risco": risks,
        "principais": highlights,
    }

def weekly_stats(db: Session, term: str | None = None) -> dict:
    return recent_stats(db, term)

def backfill_journalists(db: Session, limit: int = 50) -> dict:
    candidates = db.scalars(
        select(Article)
        .where(Article.journalist.is_(None))
        .where(~Article.url.contains("news.google.com"))
        .order_by(Article.published_at.desc())
        .limit(limit)
    ).all()
    updated = 0
    for article in candidates:
        enriched = enrich({
            "url": article.url,
            "source": article.source,
            "body": article.body,
            "journalist": article.journalist,
        })
        if enriched.get("journalist"):
            article.journalist = enriched["journalist"]
            updated += 1
    if updated:
        db.commit()
    return {"analisadas": len(candidates), "jornalistas_identificados": updated}
