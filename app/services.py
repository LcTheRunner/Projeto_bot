import json
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.classifier import classify, is_relevant, normalize, result_json
from app.collectors import rss_items, google_news_items, google_items, instagram_items, enrich
from app.config import yaml_config
from app.models import Article, Classification

NEWS_WINDOW_HOURS = 72
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

def save_item(db: Session, item: dict) -> Article | None:
    if not item.get("url") or db.scalar(select(Article).where(Article.url == item["url"])): return None
    item = dict(item)
    source_weight = float(item.pop("_source_weight", 1.0))
    skip_enrich = bool(item.pop("_skip_enrich", False))
    if not is_recent(item.get("published_at")): return None
    if not is_relevant(item.get("title", ""), item.get("body", "")): return None
    if not skip_enrich:
        item = enrich(item)
    result = classify(item["title"], item["body"], source_weight=source_weight)
    if not is_relevant(item["title"], item["body"]): return None
    keywords, evidence = result_json(result)
    article = Article(**item, section=result.section)
    article.classification = Classification(risk_score=result.risk_score, tone=result.tone, impact_score=result.impact_score, matched_keywords=keywords, evidence=evidence)
    db.add(article); db.commit(); db.refresh(article)
    return article

def collect(db: Session) -> dict:
    removed = prune_expired(db)
    sources = yaml_config("sources.yaml")
    items = rss_items() + google_news_items()
    if sources.get("google", {}).get("enabled", False):
        for query in sources.get("google", {}).get("queries", []): items += google_items(query)
    if sources.get("instagram", {}).get("enabled", False):
        for hashtag in yaml_config("keywords.yaml").get("hashtags_instagram", []): items += instagram_items(hashtag)
    unique = list({item.get("url"): item for item in items if item.get("url")}.values())
    recent = [item for item in unique if is_recent(item.get("published_at"))]
    relevant = [item for item in recent if is_relevant(item.get("title", ""), item.get("body", ""))]
    saved = sum(save_item(db, item) is not None for item in relevant)
    return {
        "encontrados": len(unique),
        "ultimas_72h": len(recent),
        "relevantes": len(relevant),
        "descartados": len(unique) - len(relevant),
        "novos": saved,
        "expirados_removidos": removed,
    }

def recent_stats(db: Session, term: str | None = None, top_limit: int = 15) -> dict:
    since = recent_cutoff()
    rows = db.execute(select(Article, Classification).join(Classification).where(Article.published_at >= since)).all()
    if term:
        needle = term.casefold(); rows = [r for r in rows if needle in (r.Article.title + " " + r.Article.body).casefold()]
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
    marica = [row for row in ordered if geographic_scope(row.Article) == "marica"]
    state_rj = [row for row in ordered if geographic_scope(row.Article) == "estado_rj"]
    national = [row for row in ordered if geographic_scope(row.Article) == "nacional"]
    marica_quota = (top_limit + 1) // 2
    state_quota = top_limit // 2
    selected = marica[:marica_quota] + state_rj[:state_quota]
    selected_ids = {row.Article.id for row in selected}
    remaining = [
        row for row in marica + state_rj + national
        if row.Article.id not in selected_ids
    ]
    selected.extend(remaining[:max(0, top_limit - len(selected))])
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
            "editoria": article.section,
            "publicada_em": article.published_at,
            "risco": classification.risk_score,
            "impacto": classification.impact_score,
            "prioridade": priority,
            "abrangencia": geographic_scope(article),
            "palavras": json.loads(classification.matched_keywords),
        })
    return {
        "periodo_horas": NEWS_WINDOW_HOURS,
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
