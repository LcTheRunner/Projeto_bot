from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import case, distinct, false, func, literal, or_, select
from sqlalchemy.orm import Session

from app.cache import TtlCache
from app.classifier import normalize
from app.config import settings
from app.models import Article, Classification, UserKeyword


RJ_LOCATIONS = [
    "rio de janeiro", "estado do rio", "governo do rio", "alerj",
    "angra dos reis", "aperibé", "araruama", "areal", "armação dos búzios", "arraial do cabo",
    "barra do piraí", "barra mansa", "belford roxo", "bom jardim", "bom jesus do itabapoana",
    "cabo frio", "cachoeiras de macacu", "cambuci", "campos dos goytacazes", "cantagalo",
    "carapebus", "cardoso moreira", "carmo", "casimiro de abreu", "comendador levy gasparian",
    "conceição de macabu", "cordeiro", "duas barras", "duque de caxias", "engenheiro paulo de frontin",
    "guapimirim", "iguaba grande", "itaboraí", "itaguaí", "italva", "itaocara", "itaperuna",
    "itatiaia", "japeri", "laje do muriaé", "macaé", "macuco", "magé", "mangaratiba",
    "maricá", "mendes", "mesquita", "miguel pereira", "miracema", "natividade", "nilópolis",
    "niterói", "nova friburgo", "nova iguaçu", "paracambi", "paraíba do sul", "paraty",
    "paty do alferes", "petrópolis", "pinheiral", "piraí", "porciúncula", "porto real",
    "quatis", "queimados", "quissamã", "resende", "rio bonito", "rio claro", "rio das flores",
    "rio das ostras", "santa maria madalena", "santo antônio de pádua", "são fidélis",
    "são francisco de itabapoana", "são gonçalo", "são joão da barra", "são joão de meriti",
    "são josé de ubá", "são josé do vale do rio preto", "são pedro da aldeia", "são sebastião do alto",
    "sapucaia", "saquarema", "seropédica", "silva jardim", "sumidouro", "tanguá",
    "teresópolis", "trajano de moraes", "três rios", "valença", "varre-sai", "vassouras",
    "volta redonda",
]
RJ_MUNICIPALITIES = ["Rio de Janeiro (capital)", *RJ_LOCATIONS[4:]]


_overview_cache = TtlCache(settings().dashboard_cache_seconds, max_entries=128)
_facet_cache = TtlCache(max(60, settings().dashboard_cache_seconds * 5), max_entries=8)


@dataclass(frozen=True)
class OverviewOptions:
    days: int = 7
    keywords: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    risks: tuple[int, ...] = ()
    tones: tuple[str, ...] = ()
    query: str | None = None
    locations: tuple[str, ...] = ()
    include_all: bool = False
    page: int = 1
    page_size: int = 100


def clear_dashboard_cache() -> None:
    _overview_cache.clear()
    _facet_cache.clear()


def _clean(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values or () if value and value.strip()))


def normalized_options(
    days: int,
    keywords: list[str] | None,
    sources: list[str] | None,
    sections: list[str] | None,
    risks: list[int] | None,
    tones: list[str] | None,
    query: str | None,
    locations: list[str] | None,
    include_all: bool,
    page: int,
    page_size: int,
) -> OverviewOptions:
    return OverviewOptions(
        days=max(1, min(days, 365)),
        keywords=_clean(keywords),
        sources=_clean(sources),
        sections=_clean(sections),
        risks=tuple(dict.fromkeys(value for value in risks or () if value in (0, 5, 10))),
        tones=_clean(tones),
        query=query.strip() if query and query.strip() else None,
        locations=_clean(locations),
        include_all=include_all,
        page=max(1, page),
        page_size=max(1, min(page_size, 200)),
    )


def _text_contains(column, value: str):
    return column.contains(normalize(value))


def _filtered_articles(db: Session, user_id: int, options: OverviewOptions):
    since = datetime.now() - timedelta(days=options.days)
    user_keywords = list(db.scalars(
        select(UserKeyword.keyword).where(UserKeyword.user_id == user_id).order_by(UserKeyword.keyword)
    ))
    normalized_user_keywords = tuple(dict.fromkeys(normalize(value) for value in user_keywords if normalize(value)))
    scope = or_(*[Article.searchable_text.contains(value) for value in normalized_user_keywords]) if normalized_user_keywords else false()

    statement = (
        select(
            Article.id.label("id"), Article.title.label("title"), Article.url.label("url"),
            Article.source.label("source"), Article.section.label("section"),
            Article.journalist.label("journalist"), Article.published_at.label("published_at"),
            Article.searchable_text.label("searchable_text"),
            Classification.risk_score.label("risk"), Classification.tone.label("tone"),
            Classification.impact_score.label("impact"),
            Classification.matched_keywords.label("matched_keywords"),
            Classification.evidence.label("evidence"),
        )
        .join(Classification, Classification.article_id == Article.id)
        .where(Article.published_at >= since, scope)
    )
    if options.keywords:
        statement = statement.where(or_(*[_text_contains(Article.searchable_text, term) for term in options.keywords]))
    if options.sources:
        statement = statement.where(func.lower(Article.source).in_([value.lower() for value in options.sources]))
    if options.sections:
        statement = statement.where(func.lower(Article.section).in_([value.lower() for value in options.sections]))
    if options.risks:
        statement = statement.where(Classification.risk_score.in_(options.risks))
    if options.tones:
        statement = statement.where(func.lower(Classification.tone).in_([value.lower() for value in options.tones]))
    if options.query:
        statement = statement.where(_text_contains(Article.searchable_text, options.query))
    if options.locations:
        if any(value.lower() == "estado_rj" for value in options.locations):
            location_terms = [*RJ_LOCATIONS, " rj "]
        else:
            location_terms = [value.replace(" (capital)", "") for value in options.locations]
        statement = statement.where(or_(*[_text_contains(Article.searchable_text, value) for value in location_terms]))
    return statement.subquery("filtered_articles"), user_keywords, since


def _label(value: str | None) -> str:
    if not value:
        return "Não identificado"
    value = value.replace("_", " ")
    return value[:1].upper() + value[1:]


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _ranked(db: Session, base, column, limit: int = 12, transform=lambda value: value) -> list[dict]:
    rows = db.execute(
        select(column, func.count().label("total"))
        .select_from(base)
        .group_by(column)
        .order_by(func.count().desc(), column.asc())
        .limit(limit)
    ).all()
    return [{"label": transform(row[0]), "value": int(row.total)} for row in rows]


def _keyword_counts(db: Session, base, user_keywords: list[str]) -> list[dict]:
    terms = [(term, normalize(term)) for term in user_keywords if normalize(term)]
    if not terms:
        return []
    expressions = [
        func.sum(case((base.c.searchable_text.contains(normalized), 1), else_=0))
        for _, normalized in terms
    ]
    values = db.execute(select(*expressions).select_from(base)).one()
    result = [
        {"label": term, "value": int(values[index] or 0)}
        for index, (term, _) in enumerate(terms)
        if values[index]
    ]
    return sorted(result, key=lambda item: (-item["value"], item["label"].casefold()))[:20]


def _timeline(db: Session, base, since: datetime) -> list[dict]:
    day_column = func.date(base.c.published_at)
    rows = db.execute(
        select(day_column, func.count()).select_from(base).group_by(day_column).order_by(day_column)
    ).all()
    values = {str(day): int(total) for day, total in rows}
    result = []
    current = since.date()
    today = date.today()
    while current <= today:
        label = current.isoformat()
        result.append({"label": label, "value": values.get(label, 0)})
        current += timedelta(days=1)
    return result


def overview(db: Session, user_id: int, options: OverviewOptions) -> dict:
    cache_key = (user_id, options)
    if not options.include_all:
        cached = _overview_cache.get(cache_key)
        if cached is not None:
            cached["cache"] = {"hit": True, "ttlSeconds": settings().dashboard_cache_seconds}
            return cached

    base, user_keywords, since = _filtered_articles(db, user_id, options)
    kpi = db.execute(
        select(
            func.count().label("articles"),
            func.count(distinct(base.c.source)).label("sources"),
            func.sum(case((base.c.risk == 10, 1), else_=0)).label("risk10"),
            func.sum(case((base.c.risk == 5, 1), else_=0)).label("risk5"),
            func.avg(base.c.impact).label("averageImpact"),
            func.sum(case((base.c.source.like("Instagram/%"), 1), else_=0)).label("instagram"),
        ).select_from(base)
    ).mappings().one()
    total = int(kpi["articles"] or 0)

    articles_statement = select(base).order_by(base.c.published_at.desc(), base.c.id.desc())
    if not options.include_all:
        articles_statement = articles_statement.offset((options.page - 1) * options.page_size).limit(options.page_size)
    rows = db.execute(articles_statement).mappings().all()
    articles = []
    for row in rows:
        item = {
            "id": row["id"], "title": row["title"], "url": row["url"], "source": row["source"],
            "section": row["section"],
            "publishedAt": row["published_at"], "risk": row["risk"], "tone": row["tone"],
            "impact": row["impact"], "keywords": _json_list(row["matched_keywords"]),
            "evidence": _json_list(row["evidence"]),
        }
        if row["journalist"] is not None:
            item["journalist"] = row["journalist"]
        articles.append(item)
    result = {
        "periodDays": options.days,
        "generatedAt": datetime.now(),
        "kpis": {
            "articles": total,
            "sources": int(kpi["sources"] or 0),
            "risk10": int(kpi["risk10"] or 0),
            "risk5": int(kpi["risk5"] or 0),
            "averageImpact": round(float(kpi["averageImpact"] or 0), 2),
            "instagram": int(kpi["instagram"] or 0),
        },
        "byRisk": _ranked(db, base, base.c.risk, transform=lambda value: f"Risco {value}"),
        "byTone": _ranked(db, base, base.c.tone, transform=_label),
        "bySource": _ranked(db, base, base.c.source),
        "bySection": _ranked(db, base, base.c.section, transform=_label),
        "byKeyword": _keyword_counts(db, base, user_keywords),
        "timeline": _timeline(db, base, since),
        "articles": articles,
        "pagination": {
            "page": 1 if options.include_all else options.page,
            "pageSize": total if options.include_all else options.page_size,
            "totalItems": total,
            "totalPages": 1 if options.include_all else math.ceil(total / options.page_size),
        },
        "cache": {"hit": False, "ttlSeconds": settings().dashboard_cache_seconds},
    }
    if not options.include_all:
        _overview_cache.set(cache_key, result)
    return result


def filters(db: Session, user_id: int) -> dict:
    global_facets = _facet_cache.get("global")
    if global_facets is None:
        global_facets = {
            "sources": list(db.scalars(select(distinct(Article.source)).order_by(Article.source))),
            "sections": list(db.scalars(select(distinct(Article.section)).order_by(Article.section))),
            "tones": list(db.scalars(select(distinct(Classification.tone)).order_by(Classification.tone))),
        }
        _facet_cache.set("global", global_facets)
    return {
        **global_facets,
        "risks": [0, 5, 10],
        "keywords": list(db.scalars(
            select(UserKeyword.keyword).where(UserKeyword.user_id == user_id).order_by(UserKeyword.keyword)
        )),
        "municipalities": [_municipality_label(value) for value in RJ_MUNICIPALITIES],
    }


def _municipality_label(value: str) -> str:
    if "(capital)" in value:
        return value
    lowercase = {"da", "das", "de", "do", "dos"}
    return " ".join(word if word in lowercase else word[:1].upper() + word[1:] for word in value.split())
