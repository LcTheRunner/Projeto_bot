from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.classifier import classify, result_json
from app.collectors import rss_items, google_items, instagram_items, enrich
from app.config import yaml_config
from app.models import Article, Classification

def save_item(db: Session, item: dict) -> Article | None:
    if not item.get("url") or db.scalar(select(Article).where(Article.url == item["url"])): return None
    item = enrich(item)
    result = classify(item["title"], item["body"])
    keywords, evidence = result_json(result)
    article = Article(**item, section=result.section)
    article.classification = Classification(risk_score=result.risk_score, tone=result.tone, impact_score=result.impact_score, matched_keywords=keywords, evidence=evidence)
    db.add(article); db.commit(); db.refresh(article)
    return article

def collect(db: Session) -> dict:
    items = rss_items()
    for term in yaml_config("keywords.yaml")["monitorados"]: items += google_items(term)
    if yaml_config("sources.yaml").get("instagram", {}).get("enabled", False):
        for hashtag in yaml_config("keywords.yaml").get("hashtags_instagram", []): items += instagram_items(hashtag)
    saved = sum(save_item(db, item) is not None for item in items)
    return {"encontrados": len(items), "novos": saved}

def weekly_stats(db: Session, term: str | None = None) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=7)
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
    return {"periodo_dias": 7, "termo": term, "total": len(rows), "por_veiculo": count("source"), "por_editoria": count("section"), "por_jornalista": count("journalist"), "por_risco": risks}
