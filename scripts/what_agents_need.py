#!/usr/bin/env python3
"""Platform env checklist (SET/MISSING only). Run: python scripts/what_agents_need.py"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"

SECTIONS: list[tuple[str, str]] = [
    ("newsapi", "NewsAPI"),
    ("linkedin", "LinkedIn"),
    ("x / twitter", "X"),
    ("instagram", "Instagram"),
    ("telegram", "Telegram"),
    ("smtp", "SMTP"),
    ("hubspot", "HubSpot"),
    ("twilio", "Twilio"),
    ("canva", "Canva"),
]

VAR_RE = re.compile(r"^(?:#\s*)?(?:export\s+)?([A-Z][A-Z0-9_]*)=")

ZERO_KEYS = [
    "Marketing drafts, campaigns, storyboards (offline generation)",
    "Run now -> draft queue; approve attempts real send (configuration_required if no creds)",
    "Remotive jobs connector + CoinGecko market data (public APIs, no keys)",
]


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        key, _, val = s.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def platform_vars_from_example(text: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {name: [] for _, name in SECTIONS}
    current: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("#"):
            m = VAR_RE.match(s)
            if m and current and m.group(1) not in groups[current]:
                groups[current].append(m.group(1))
            continue
        if re.match(r"^#\s*---", s):
            current = None
            continue
        lower = s.lower()
        if "\u2014" in s or " - " in s or re.search(r"\s-\s", s):
            matched = False
            for key, name in SECTIONS:
                if key in lower:
                    current = name
                    matched = True
                    break
            if not matched:
                current = None
        m = VAR_RE.match(s)
        if m and current and m.group(1) not in groups[current]:
            groups[current].append(m.group(1))
    return groups


def is_set(name: str, file_vals: dict[str, str]) -> bool:
    return bool((os.environ.get(name) or file_vals.get(name) or "").strip())


def main() -> None:
    file_vals = parse_env(ENV_FILE)
    platforms = platform_vars_from_example(EXAMPLE.read_text(encoding="utf-8", errors="replace"))
    src = str(ENV_FILE) if ENV_FILE.is_file() else "(no .env - os.environ only)"

    print("Veridiq - platform env checklist")
    print("=" * 36)
    print("\nWorks with zero API keys:")
    for item in ZERO_KEYS:
        print(f"  - {item}")

    print(f"\nPlatform vars from .env.example ({src}):")
    for _, name in SECTIONS:
        vars_ = platforms.get(name) or []
        if not vars_:
            continue
        print(f"\n{name}")
        for var in vars_:
            print(f"  {var}: {'SET' if is_set(var, file_vals) else 'MISSING'}")

    print("\nTip: copy .env.example -> .env, fill vars, restart backend.")


if __name__ == "__main__":
    main()
