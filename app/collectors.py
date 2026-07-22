from datetime import datetime, timezone
from urllib.parse import urlparse
import feedparser, httpx, trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from app.config import settings, yaml_config

def rss_items() -> list[dict]:
    output = []
    for source in yaml_config("sources.yaml").get("rss", []):
        feed = feedparser.parse(source["url"])
        for item in feed.entries:
            output.append({"title": item.get("title", ""), "url": item.get("link", ""), "body": item.get("summary", ""), "source": source["nome"], "published_at": _date(item.get("published"))})
    return output

def google_items(query: str) -> list[dict]:
    cfg = settings()
    if not cfg.google_api_key or not cfg.google_cse_id: return []
    response = httpx.get("https://customsearch.googleapis.com/customsearch/v1", params={"key": cfg.google_api_key, "cx": cfg.google_cse_id, "q": query, "dateRestrict": "d7"}, timeout=30).raise_for_status().json()
    return [{"title": x["title"], "url": x["link"], "body": x.get("snippet", ""), "source": urlparse(x["link"]).netloc, "published_at": datetime.now(timezone.utc)} for x in response.get("items", [])]

def instagram_items(hashtag: str) -> list[dict]:
    cfg = settings()
    if not cfg.instagram_access_token or not cfg.instagram_user_id: return []
    base = f"https://graph.facebook.com/{cfg.instagram_graph_version}"
    common = {"access_token": cfg.instagram_access_token}
    found = httpx.get(f"{base}/ig_hashtag_search", params={**common, "user_id": cfg.instagram_user_id, "q": hashtag}, timeout=30).raise_for_status().json().get("data", [])
    if not found: return []
    media = httpx.get(f"{base}/{found[0]['id']}/recent_media", params={**common, "user_id": cfg.instagram_user_id, "fields": "id,caption,media_url,permalink,timestamp,username"}, timeout=30).raise_for_status().json().get("data", [])
    return [{"title": (x.get("caption") or f"Instagram #{hashtag}")[:1000], "url": x.get("permalink", ""), "body": x.get("caption", ""), "source": f"Instagram/@{x.get('username', 'desconhecido')}", "published_at": _date(x.get("timestamp")), "journalist": x.get("username")} for x in media]

def enrich(item: dict) -> dict:
    if item.get("source", "").startswith("Instagram/"):
        return item
    try:
        html = httpx.get(item["url"], follow_redirects=True, timeout=20, headers={"User-Agent": "MediaMonitor/1.0"}).text
        item["body"] = trafilatura.extract(html, include_comments=False) or item["body"]
        soup = BeautifulSoup(html, "html.parser")
        author = soup.select_one('[rel="author"], [class*="author"], [class*="autor"]')
        item["journalist"] = author.get_text(" ", strip=True)[:255] if author else None
    except Exception:
        item["journalist"] = None
    return item

def _date(value):
    try: return dateparser.parse(value)
    except Exception: return datetime.now(timezone.utc)
