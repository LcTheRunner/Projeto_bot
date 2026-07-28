import logging
import math
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
import feedparser, httpx, trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from app.config import settings, yaml_config

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "MediaMonitor/1.0"}

def _feed_items(name: str, url: str, weight: float = 1.0, publisher_from_entry: bool = False) -> list[dict]:
    try:
        response = httpx.get(url, follow_redirects=True, timeout=20, headers=HEADERS)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as exc:
        logger.warning("Falha no feed %s: %s", name, type(exc).__name__)
        return []
    output = []
    for item in feed.entries:
        source = name
        entry_source = item.get("source")
        if publisher_from_entry and isinstance(entry_source, dict):
            source = entry_source.get("title") or name
        summary = BeautifulSoup(item.get("summary", "") or "", "html.parser").get_text(" ", strip=True)
        output.append({
            "title": item.get("title", "") or "",
            "url": item.get("link", "") or "",
            "body": summary,
            "source": source,
            "published_at": _date(item.get("published") or item.get("updated")),
            "_source_weight": weight,
            "journalist": _clean_author(item.get("author") or item.get("dc_creator")),
        })
    return output

def rss_items() -> list[dict]:
    output = []
    for source in yaml_config("sources.yaml").get("rss", []):
        output.extend(_feed_items(source["nome"], source["url"], float(source.get("peso", 1.0))))
    return output

def google_news_items(extra_queries: list[str] | None = None) -> list[dict]:
    cfg = yaml_config("sources.yaml").get("google_news", {})
    if not cfg.get("enabled", False):
        return []
    output = []
    hours = int(cfg.get("horas", 72))
    days = math.ceil(hours / 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    outlet_queries = [outlet["query"] for outlet in cfg.get("outlets", []) if outlet.get("query")]
    queries = list(dict.fromkeys([*cfg.get("queries", []), *outlet_queries, *(extra_queries or [])]))[:80]
    for query in queries:
        params = urlencode({"q": f"{query} when:{days}d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
        items = _feed_items(
            "Google Notícias",
            f"https://news.google.com/rss/search?{params}",
            float(cfg.get("peso", 1.0)),
            publisher_from_entry=True,
        )
        for item in items:
            item["_skip_enrich"] = True
        output.extend(item for item in items if _aware(item["published_at"]) >= cutoff)
    return output

def google_items(query: str) -> list[dict]:
    cfg = settings()
    if not cfg.google_api_key or not cfg.google_cse_id: return []
    try:
        response = httpx.get(
            "https://customsearch.googleapis.com/customsearch/v1",
            params={"key": cfg.google_api_key, "cx": cfg.google_cse_id, "q": query, "dateRestrict": "d7"},
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("Falha na Google Custom Search: HTTP %s", exc.response.status_code)
        return []
    except httpx.HTTPError as exc:
        logger.warning("Falha na Google Custom Search: %s", type(exc).__name__)
        return []
    response = response.json()
    return [{"title": x["title"], "url": x["link"], "body": x.get("snippet", ""), "source": urlparse(x["link"]).netloc, "published_at": datetime.now(timezone.utc), "_source_weight": 1.0} for x in response.get("items", [])]

def instagram_items(hashtag: str) -> list[dict]:
    cfg = settings()
    if not cfg.instagram_access_token or not cfg.instagram_user_id: return []
    base = f"https://graph.facebook.com/{cfg.instagram_graph_version}"
    common = {"access_token": cfg.instagram_access_token}
    found = httpx.get(f"{base}/ig_hashtag_search", params={**common, "user_id": cfg.instagram_user_id, "q": hashtag}, timeout=30).raise_for_status().json().get("data", [])
    if not found: return []
    media = httpx.get(f"{base}/{found[0]['id']}/recent_media", params={**common, "user_id": cfg.instagram_user_id, "fields": "id,caption,media_url,permalink,timestamp,username"}, timeout=30).raise_for_status().json().get("data", [])
    return [{"title": (x.get("caption") or f"Instagram #{hashtag}")[:1000], "url": x.get("permalink", ""), "body": x.get("caption") or "", "source": f"Instagram/@{x.get('username', 'desconhecido')}", "published_at": _date(x.get("timestamp")), "journalist": x.get("username"), "_source_weight": 0.9} for x in media]

def enrich(item: dict) -> dict:
    if item.get("source", "").startswith("Instagram/"):
        return item
    try:
        response = httpx.get(item["url"], follow_redirects=True, timeout=20, headers=HEADERS)
        response.raise_for_status()
        html = response.text
        extracted = trafilatura.extract(html, include_comments=False)
        if extracted:
            item["body"] = f"{item.get('body', '')}\n\n{extracted}".strip()
        soup = BeautifulSoup(html, "html.parser")
        item["journalist"] = _extract_author(soup) or item.get("journalist")
    except Exception:
        item["journalist"] = item.get("journalist")
    return item

def _extract_author(soup: BeautifulSoup) -> str | None:
    meta_candidates = [
        ("name", "author"), ("property", "article:author"), ("name", "byl"),
        ("name", "parsely-author"), ("itemprop", "author"),
    ]
    for attribute, value in meta_candidates:
        node = soup.find("meta", attrs={attribute: re.compile(f"^{re.escape(value)}$", re.I)})
        author = _clean_author(node.get("content") if node else None)
        if author:
            return author
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
            for node in _json_nodes(payload):
                if not isinstance(node, dict) or "author" not in node:
                    continue
                authors = node["author"] if isinstance(node["author"], list) else [node["author"]]
                names = [_clean_author(author.get("name") if isinstance(author, dict) else author) for author in authors]
                names = [name for name in names if name]
                if names:
                    return ", ".join(names)[:255]
        except (ValueError, TypeError):
            pass
    selectors = [
        '[rel="author"]', '[itemprop="author"] [itemprop="name"]', '.author-name',
        '.article-author', '.post-author', '.byline', '[class*="autor"]',
        '[class*="author"]', '[data-testid*="author"]', '[data-testid*="byline"]',
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        author = _clean_author(node.get_text(" ", strip=True) if node else None)
        if author:
            return author
    # Alguns veículos exibem a assinatura apenas como texto visível: "Por Redação g1".
    text = soup.get_text("\n", strip=True)
    match = re.search(
        r"(?:^|[|•·\n])\s*por\s+([^|•·\n]{3,120}?)(?=\s+\d{1,2}/\d{1,2}/\d{4}|\s+publicad[oa]|\s+atualizad[oa]|$)",
        text,
        re.I,
    )
    if match:
        return _clean_author(match.group(1))
    return None

def _json_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _json_nodes(item)
    elif isinstance(value, dict):
        yield value
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                yield from _json_nodes(value[key])

def _clean_author(value) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"^(por|by)\s+", "", text, flags=re.I).strip(" -|")
    # "Redação g1", por exemplo, é uma assinatura editorial válida e deve ser mantida.
    rejected = ("redação", "da redação", "editorial", "autor", "author", "equipe")
    if len(text) < 3 or text.casefold() in rejected:
        return None
    return text[:255]

def _date(value):
    try: return dateparser.parse(value)
    except Exception: return datetime.now(timezone.utc)

def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
