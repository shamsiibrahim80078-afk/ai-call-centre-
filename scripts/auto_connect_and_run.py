#!/usr/bin/env python3
"""Auto-probe platforms + run agencies without inventing OAuth credentials.

  python scripts/auto_connect_and_run.py

LinkedIn age gates / Meta / Google OAuth apps can ONLY be created by a human
with an eligible account. This script never fabricates those tokens.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env like app.py
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

os.environ.setdefault("VERIDIQ_MIN_VISIBLE_SEC", "0")


def main() -> int:
    from database import initialize_database
    from veridiq.runtime.auto_agency import run_auto_agency

    initialize_database()
    print("=" * 60)
    print("VERIDIQ AUTO CONNECT + AGENCY RUN")
    print("=" * 60)
    print(
        "Note: LinkedIn/Meta/Google developer apps require YOUR eligible account.\n"
        "Age-restricted LinkedIn cannot be bypassed by this script.\n"
    )
    result = run_auto_agency(run_cascade=True, run_marketing=True, approve_sends=False)
    ready = result.get("probe", {}).get("ready") or []
    blocked = result.get("probe", {}).get("blocked") or []
    print(f"Ready platforms ({len(ready)}): {', '.join(ready) or '—'}")
    print(f"Blocked / needs human keys ({len(blocked)}):")
    for b in blocked:
        print(f"  - {b.get('platform')}: {b.get('reason')}")
        if b.get("platform") == "linkedin":
            print(f"      {b.get('note', '')[:120]}")
    cascade = result.get("cascade") or {}
    print(f"\nCascade ok={cascade.get('ok')} summary={cascade.get('summary', cascade.get('error', '—'))}")
    marketing = result.get("marketing") or {}
    print(
        f"Marketing ok={marketing.get('ok')} channels={marketing.get('channels_used')} "
        f"agents={len(marketing.get('agents') or [])}"
    )
    print("\nFull JSON:")
    print(json.dumps(result, indent=2, default=str)[:8000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
