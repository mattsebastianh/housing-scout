import re
from typing import Any, Iterable

import feedparser

_KEYWORDS = re.compile(
    r"vivienda|alquiler|zonas tensionadas|tope de precios|inmobiliari|"
    r"impuesto sobre bienes inmuebles|ibi|propiedad horizontal",
    re.IGNORECASE,
)

FEEDS = {
    "BOE": "https://www.boe.es/rss/boe.php",
    "DOGC": "https://dogc.gencat.cat/rss/dogc.xml",
    "DOGV": "https://www.dogv.gva.es/feeds/RSS.do",
}


def filter_relevant(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        i for i in items
        if _KEYWORDS.search((i.get("title") or "") + " " + (i.get("summary") or ""))
    ]


def fetch_alerts(max_per_feed: int = 30) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source, url in FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_per_feed]:
            out.append({
                "source": source,
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
    return filter_relevant(out)
