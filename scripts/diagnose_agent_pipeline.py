#!/usr/bin/env python3
"""Diagnose Marketing → Postings → Calling pipeline (read-only + light probes).

Usage:
  python scripts/diagnose_agent_pipeline.py
  python scripts/diagnose_agent_pipeline.py --base http://127.0.0.1:8002
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _get(url: str, timeout: float = 8.0) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw[:400]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        return exc.code, {"error": body or str(exc)}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def check_imports() -> dict:
    mods = [
        "veridiq.marketing.postings_handoff",
        "veridiq.calling.budget",
        "veridiq.calling.timed_calls",
        "veridiq.calling.chain_hooks",
        "veridiq.calling.agent_presence",
        "veridiq.calling.worker",
        "veridiq.postings.studio",
    ]
    out = {}
    for name in mods:
        try:
            __import__(name)
            out[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"FAIL: {exc}"[:160]
    return out


def check_handoff_dir() -> dict:
    try:
        from veridiq.marketing.postings_handoff import HANDOFF_DIR, _enabled

        HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "enabled": _enabled(),
            "dir": str(HANDOFF_DIR),
            "artifacts": len(list(HANDOFF_DIR.glob("handoff-*.json"))),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose agent pipeline health")
    parser.add_argument("--base", default="http://127.0.0.1:8002", help="API base URL")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    report: dict = {
        "imports": check_imports(),
        "handoff_dir": check_handoff_dir(),
        "http": {},
    }

    for label, path in [
        ("health", "/api/v1/health"),
        ("pipeline_health", "/api/v1/veridiq/agents/pipeline/health"),
        ("postings_agent", "/api/v1/veridiq/postings/agent"),
        ("calling_budget", "/api/v1/veridiq/calling/budget"),
        ("calling_timed", "/api/v1/veridiq/calling/timed"),
        ("calling_meetings", "/api/v1/veridiq/calling/meetings"),
        ("livekit_status", "/api/v1/veridiq/calling/livekit/status"),
        ("calling_worker", "/api/v1/veridiq/calling/worker/status"),
    ]:
        status, body = _get(f"{base}{path}")
        report["http"][label] = {"status": status, "body": body}

    import_ok = all(v == "ok" for v in report["imports"].values())
    http_ok = all(
        isinstance(v.get("status"), int) and 200 <= v["status"] < 300 for v in report["http"].values()
    )
    report["ok"] = import_ok and http_ok and bool(report["handoff_dir"].get("ok"))

    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
