"""
agents/gdelt_scanner.py — GDELT Multi-Source NLP Scanner

Polls GDELT DOC API and various Indian RSS feeds to extract logistics disruptions.
Uses spaCy NER for location extraction and simple keyword matching for classification.
Implements a sliding window deduplication via Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass

import feedparser
import httpx
import spacy
import structlog

from core.config import settings
from core.redis import redis_client

log = structlog.get_logger(__name__)

# ── 1. Init spaCy ───────────────────────────────────────────

try:
    nlp = spacy.load("en_core_web_sm")
    log.info("gdelt.spacy_loaded")
except Exception as exc:  # noqa: BLE001
    log.warning("gdelt.spacy_load_failed", error=str(exc))
    nlp = None

# ── 2. Constants ─────────────────────────────────────────────

# Keyword -> Category mapping
_RAW_KEYWORDS = {
    "strike": [
        "trucker strike",
        "driver agitation",
        "lorry bandh",
        "transport strike",
        "chakka jam",
    ],
    "flood": ["highway flooded", "nh closed flood", "road blocked rain", "bridge washed", "flood"],
    "fuel": ["fuel scarcity", "petrol shortage", "diesel crisis", "truckers halt fuel"],
    "tariff": ["export ban", "import duty", "trade restriction", "border closure tariff"],
    "port": [
        "port congestion",
        "container shortage",
        "port strike",
        "vessel delay jnpt",
        "mundra port",
    ],
    "cyber": ["ransomware logistics", "shipping system hack", "supply chain cyber"],
}

DISRUPTION_KEYWORDS: dict[str, list[re.Pattern[str]]] = {
    cat: [re.compile(kw, re.IGNORECASE) for kw in kws] for cat, kws in _RAW_KEYWORDS.items()
}

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_TOI_RSS = "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"  # TOI Business
_PTI_RSS = "https://www.ptinews.com/rss"
_PIB_RSS = "https://pib.gov.in/RssMain.aspx"

# ── 3. Models ────────────────────────────────────────────────


@dataclass
class Article:
    title: str
    url: str
    source: str
    timestamp: str


@dataclass
class DisruptionAlert:
    locations: list[str]
    disruption_type: str
    source_count: int
    confidence: float
    headlines: list[str]
    severity: str
    lat: float = 0.0
    lon: float = 0.0

    @property
    def location(self) -> str:
        """Compat property for sentinel_agent.py"""
        return self.locations[0] if self.locations else "unknown"

    @property
    def alert_type(self) -> str:
        """Compat property for sentinel_agent.py"""
        return self.disruption_type

    @property
    def description(self) -> str:
        """Compat property for sentinel_agent.py"""
        return " | ".join(self.headlines)


# ── 4. Extractors ────────────────────────────────────────────


async def fetch_gdelt() -> list[Article]:
    log.debug("fetch_gdelt.start")
    params = {
        "query": "India (strike OR flood OR fuel OR tariff OR port OR cyber)",
        "mode": "artlist",
        "maxrecords": 25,
        "format": "json",
    }
    articles = []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(_GDELT_URL, params=params, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            for art in data.get("articles", []):
                articles.append(
                    Article(
                        title=art.get("title", ""),
                        url=art.get("url", ""),
                        source="gdelt",
                        timestamp=art.get("seendate", ""),
                    )
                )
        log.info("fetch_gdelt.success", count=len(articles))
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_gdelt.failed", error=str(exc))
    return articles


async def fetch_rss(url: str, source_name: str) -> list[Article]:
    log.debug(f"fetch_{source_name}.start")
    articles = []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()

            # Use feedparser to handle RSS/XML safely
            feed = feedparser.parse(resp.text)
            if feed.bozo and feed.bozo_exception:
                log.warning(
                    f"fetch_{source_name}.xml_parse_warning", error=str(feed.bozo_exception)
                )

            for entry in feed.entries[:25]:
                articles.append(
                    Article(
                        title=entry.get("title", ""),
                        url=entry.get("link", ""),
                        source=source_name,
                        timestamp=entry.get("published", ""),
                    )
                )
        log.info(f"fetch_{source_name}.success", count=len(articles))
    except Exception as exc:  # noqa: BLE001
        log.warning(f"fetch_{source_name}.failed", error=str(exc))
    return articles


# ── 5. Geocoding ─────────────────────────────────────────────


async def geocode_location(location: str) -> tuple[float, float] | None:
    if not location or location.lower() == "unknown":
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{location}, India", "format": "json", "limit": 1}
    headers = {"User-Agent": "LogistiQ-AI/1.0 (contact@logistiq.ai)"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                log.info("geocode_location.success", location=location)
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as exc:  # noqa: BLE001
        log.warning("geocode_location.failed", location=location, error=str(exc))

    return None


# ── 6. Pipeline ──────────────────────────────────────────────


def _classify_article(title: str) -> str | None:
    for dtype, patterns in DISRUPTION_KEYWORDS.items():
        for pat in patterns:
            if pat.search(title):
                return dtype
    return None


def _extract_locations(title: str) -> list[str]:
    if not nlp:
        return []
    doc = nlp(title)
    locs = []
    for ent in doc.ents:
        if ent.label_ in ("GPE", "ORG"):
            locs.append(ent.text)
    return list(set(locs))


async def scan_gdelt_news() -> list[DisruptionAlert]:
    """Execute the full multi-source NLP pipeline."""
    if not settings.PHASE_2_ENABLED:
        log.info("gdelt_scanner.aborted", reason="phase_2_disabled")
        return []

    log.info("gdelt_scanner.pipeline_start")

    # 1. Concurrent Fetch
    tasks = [
        fetch_gdelt(),
        fetch_rss(_TOI_RSS, "toi"),
        fetch_rss(_PTI_RSS, "pti"),
        fetch_rss(_PIB_RSS, "pib"),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_articles: list[Article] = []
    for res in results:
        if isinstance(res, list):
            all_articles.extend(res)

    # 2. Dedup
    seen_hashes = set()
    unique_articles: list[Article] = []
    for art in all_articles:
        if not art.url:
            continue
        h = hashlib.md5(art.url.encode()).hexdigest()  # noqa: S324
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_articles.append(art)

    log.info("gdelt_scanner.dedup_complete", total=len(all_articles), unique=len(unique_articles))

    alerts_created: list[DisruptionAlert] = []

    # 3 & 4. Process articles (NLP & Classification)
    for art in unique_articles:
        dtype = _classify_article(art.title)
        if not dtype:
            continue

        locs = _extract_locations(art.title)
        if not locs:
            locs = ["unknown"]

        # 5. Redis sliding window deduplication
        for loc in locs:
            loc_slug = re.sub(r"[^a-z0-9]", "", loc.lower())
            if not loc_slug:
                continue

            redis_key = f"gdelt:{loc_slug}:{dtype}"
            count = 1
            try:
                # Increment and set TTL if new
                count = await redis_client.incr(redis_key)
                if count == 1:
                    await redis_client.expire(redis_key, 1800)  # 30 minute sliding window
            except Exception as exc:  # noqa: BLE001
                log.warning("redis_incr.failed", error=str(exc))

            # 6 & 7. Check threshold and Geocode
            if count == 3:  # Only fire exactly when it hits threshold 3
                lat, lon = 0.0, 0.0
                coords = await geocode_location(loc)
                if coords:
                    lat, lon = coords

                alert = DisruptionAlert(
                    locations=[loc],
                    disruption_type=dtype,
                    source_count=count,
                    confidence=0.85,
                    headlines=[art.title],
                    severity="high" if count < 5 else "critical",
                    lat=lat,
                    lon=lon,
                )
                alerts_created.append(alert)
                log.info("gdelt_scanner.alert_created", type=dtype, location=loc)

    return alerts_created
