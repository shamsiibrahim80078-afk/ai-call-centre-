"""Optional live probe for Fireworks AI (reads .env; never prints full key).

Usage:
  python scripts/probe_fireworks.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from veridiq.integrations.llm import fireworks  # noqa: E402

key = os.environ.get("VERIDIQ_FIREWORKS_API_KEY", "")
print("key_present:", bool(key))
print("key_prefix:", (key[:4] + "...") if len(key) >= 4 else "(empty)")
print("default_model:", fireworks.DEFAULT_MODEL)
result = fireworks.test_connection()
# Redact key if somehow echoed
msg = str(result.get("message") or "")
if key and len(key) > 8:
    msg = msg.replace(key, key[:4] + "...REDACTED")
print("status:", result.get("status"), "ok:", result.get("ok"))
print("api_response_status:", result.get("api_response_status"))
print("message:", msg)
if result.get("attempts"):
    print("attempts:", result["attempts"])
