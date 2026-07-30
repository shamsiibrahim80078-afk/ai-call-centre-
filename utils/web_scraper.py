"""
Web Scraper — download and parse business websites for scout intelligence.
Uses requests + stdlib HTML parsing (html.parser) with optional regex enrichment.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

USER_AGENT = (
    "SovereignSwarmScout/1.0 (+https://localhost; autonomous-business-scout)"
)
DEFAULT_TIMEOUT = 20

PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}"
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SOCIAL_DOMAINS = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
)


class _PageParser(HTMLParser):
    """Lightweight HTML extractor for title, meta, links, phones, and text blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.anchors: list[tuple[str, str]] = []
        self.texts: list[str] = []
        self._capture_title = False
        self._ignore_depth = 0
        self._current_href: Optional[str] = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        lower = tag.lower()
        if lower in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if lower == "title":
            self._capture_title = True
        elif lower == "meta":
            name = (attr_map.get("name") or attr_map.get("property") or "").lower()
            content = attr_map.get("content", "").strip()
            if name and content:
                self.meta[name] = content
        elif lower == "a":
            href = attr_map.get("href", "").strip()
            self._current_href = href or None
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if self._ignore_depth:
            return
        if lower == "title":
            self._capture_title = False
        elif lower == "a" and self._current_href is not None:
            text = " ".join(self._anchor_text).strip()
            self.anchors.append((self._current_href, text))
            self._current_href = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._capture_title:
            self.title_parts.append(text)
        if self._current_href is not None:
            self._anchor_text.append(text)
        self.texts.append(text)


def _clean_phone(raw: str) -> Optional[str]:
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7 or len(digits) > 15:
        return None
    return raw.strip()


def _guess_industry(text: str, meta: dict[str, str]) -> Optional[str]:
    blob = f"{meta.get('description', '')} {text[:2000]}".lower()
    mapping = [
        ("restaurant", ("restaurant", "dining", "menu", "cafe")),
        ("healthcare", ("clinic", "dental", "medical", "health")),
        ("legal", ("attorney", "lawyer", "law firm", "legal")),
        ("real_estate", ("real estate", "realtor", "property")),
        ("saas", ("software", "saas", "platform", "api")),
        ("ecommerce", ("shop", "cart", "checkout", "store")),
        ("construction", ("construction", "contractor", "builder")),
        ("fitness", ("gym", "fitness", "workout")),
        ("education", ("school", "course", "academy", "tuition")),
        ("marketing", ("marketing", "seo", "advertising", "agency")),
    ]
    for industry, keywords in mapping:
        if any(k in blob for k in keywords):
            return industry
    return meta.get("og:type") or None


def _extract_location(text: str, meta: dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    city = meta.get("geo.placename") or meta.get("og:locality")
    country = meta.get("geo.country") or meta.get("og:country-name")
    loc_match = re.search(
        r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*([A-Z]{2}|[A-Z][a-z]+)\b",
        text[:3000],
    )
    if loc_match and not city:
        city = loc_match.group(1)
        maybe_country = loc_match.group(2)
        if len(maybe_country) > 2:
            country = country or maybe_country
    return city, country


def scrape_website(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """
    Download a webpage and extract structured business signals.
    Returns a normalized scout payload.
    """
    if not url or not str(url).strip():
        raise ValueError("url is required.")

    target = str(url).strip()
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    response = requests.get(
        target,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = response.text
    final_url = str(response.url)

    parser = _PageParser()
    parser.feed(html)
    parser.close()

    title = " ".join(parser.title_parts).strip() or None
    body_text = " ".join(parser.texts)
    about = (
        parser.meta.get("description")
        or parser.meta.get("og:description")
        or (body_text[:500] if body_text else None)
    )

    emails = sorted({m.group(0).lower() for m in EMAIL_RE.finditer(html)})
    phones: list[str] = []
    seen_phones: set[str] = set()
    for match in PHONE_RE.finditer(html):
        cleaned = _clean_phone(match.group(0))
        if cleaned and cleaned not in seen_phones:
            seen_phones.add(cleaned)
            phones.append(cleaned)

    social_links: list[str] = []
    for href, _text in parser.anchors:
        absolute = urljoin(final_url, href)
        host = urlparse(absolute).netloc.lower()
        if any(domain in host for domain in SOCIAL_DOMAINS):
            if absolute not in social_links:
                social_links.append(absolute)

    industry = _guess_industry(body_text, parser.meta)
    city, country = _extract_location(body_text, parser.meta)
    business_name = (
        parser.meta.get("og:site_name")
        or (title.split("|")[0].strip() if title else None)
        or (title.split("-")[0].strip() if title else None)
        or urlparse(final_url).netloc
    )

    return {
        "business_name": business_name,
        "website": final_url.rstrip("/"),
        "phone": phones[0] if phones else None,
        "phones": phones[:10],
        "email": emails[0] if emails else None,
        "emails": emails[:10],
        "social_links": social_links[:20],
        "about": about,
        "industry": industry,
        "location": {"city": city, "country": country},
        "city": city,
        "country": country,
        "title": title,
        "meta": {
            "description": parser.meta.get("description"),
            "og:title": parser.meta.get("og:title"),
        },
        "html_length": len(html),
        "text_length": len(body_text),
        "raw_text_sample": body_text[:1200],
        "status_code": response.status_code,
    }


def _self_test() -> None:
    print("=" * 60)
    print("WEB SCRAPER — SELF-TEST")
    print("=" * 60)

    result = scrape_website("https://example.com")
    assert result["status_code"] == 200
    assert result["website"]
    assert result["business_name"]
    assert result["html_length"] > 0
    print(f"[OK] business_name={result['business_name']}")
    print(f"[OK] website={result['website']}")
    print(f"[OK] title={result.get('title')}")
    print(f"[OK] about={(result.get('about') or '')[:120]}")
    print(f"[OK] phones={result.get('phones')}")
    print(f"[OK] emails={result.get('emails')}")
    print(f"[OK] social_links={result.get('social_links')}")
    print(f"[OK] industry={result.get('industry')}")
    print(f"[OK] location={result.get('location')}")
    print("=" * 60)
    print("WEB SCRAPER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
