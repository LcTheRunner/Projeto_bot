import logging
import math
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
        })
    return output

def rss_items() -> list[dict]:
    output = []
    for source in yaml_config("sources.yaml").get("rss", []):
        output.extend(_feed_items(source["nome"], source["url"], float(source.get("peso", 1.0))))
    return output

def google_news_items() -> list[dict]:
    cfg = yaml_config("sources.yaml").get("google_news", {})
    if not cfg.get("enabled", False):
        return []
    output = []
    hours = int(cfg.get("horas", 72))
    days = math.ceil(hours / 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for query in cfg.get("queries", []):
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
    response = httpx.get("https://customsearch.googleapis.com/customsearch/v1", params={"key": cfg.google_api_key, "cx": cfg.google_cse_id, "q": query, "dateRestrict": "d7"}, timeout=30).raise_for_status().json()
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
        author = soup.select_one('[rel="author"], [class*="author"], [class*="autor"]')
        item["journalist"] = author.get_text(" ", strip=True)[:255] if author else None
    except Exception:
        item["journalist"] = None
    return item

def _date(value):
    try: return dateparser.parse(value)
    except Exception: return datetime.now(timezone.utc)

def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
