"""End-to-end production validation for VERIDIQ localhost deployment."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8001"
UI = "http://127.0.0.1:5173"
REPORT = ROOT / "logs" / "production_readiness_report.json"


def check(name: str, fn):
    started = time.perf_counter()
    try:
        detail = fn()
        return {
            "name": name,
            "ok": True,
            "detail": detail,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "detail": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def main() -> int:
    results = []

    results.append(
        check("frontend_up", lambda: {"status": requests.get(UI, timeout=5).status_code})
    )
    results.append(
        check(
            "backend_health",
            lambda: requests.get(f"{API}/api/v1/health", timeout=5).json(),
        )
    )
    results.append(
        check(
            "brand_architecture",
            lambda: (
                lambda d: (
                    d
                    if d.get("architecture", {}).get("orchestrator") == "LangGraph"
                    else (_ for _ in ()).throw(AssertionError(d))
                )
            )(requests.get(f"{API}/api/v1/brand", timeout=5).json()),
        )
    )
    results.append(
        check(
            "agent_connectivity",
            lambda: (
                lambda d: d if d.get("ok") else (_ for _ in ()).throw(AssertionError(d))
            )(requests.get(f"{API}/api/v1/veridiq/agents/connectivity", timeout=10).json()),
        )
    )
    results.append(
        check(
            "system_status",
            lambda: requests.get(f"{API}/api/v1/veridiq/system", timeout=30).json(),
        )
    )
    results.append(
        check(
            "auth_login",
            lambda: (
                lambda d: {"email": d["user"]["email"], "token": bool(d.get("access_token"))}
            )(
                requests.post(
                    f"{API}/api/v1/auth/login",
                    json={"email": "admin@veridiq.ai", "password": "VeridiqAdmin!23"},
                    timeout=10,
                ).json()
            ),
        )
    )

    def verify_sync():
        r = requests.post(
            f"{API}/api/v1/veridiq/verify",
            json={
                "text": "Officials confirmed the treaty was signed on Monday in Geneva.",
                "title": "Prod validation",
            },
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        assert body.get("status") == "completed"
        assert body.get("orchestrator") == "LangGraph" or "truth_score" in body
        assert Path(body["report_path"]).exists()
        return {"truth_score": body.get("truth_score"), "job_id": body.get("job_id")}

    results.append(check("pipeline_verify_pdf", verify_sync))

    def sse_async():
        q = requests.post(
            f"{API}/api/v1/veridiq/verify",
            json={"text": "Markets rose after the Fed held rates.", "async_mode": True},
            timeout=20,
        )
        q.raise_for_status()
        job = q.json()["job_uuid"]
        stages = []
        with requests.get(f"{API}/api/v1/veridiq/jobs/{job}/events", stream=True, timeout=180) as stream:
            for line in stream.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                stages.append(ev.get("stage"))
                if ev.get("stage") in {"completed", "failed", "stream_end"}:
                    break
        assert any(s in stages for s in ("orchestrator", "queued", "pipeline_start", "route"))
        assert "completed" in stages or "stream_end" in stages
        return {"stages": stages[:12], "count": len(stages)}

    results.append(check("sse_stream", sse_async))

    def each_agent_api():
        agents = requests.get(f"{API}/api/v1/veridiq/agents", timeout=10).json()["agents"]
        sample = {
            "text": "Revenue grew according to the CFO statement last quarter.",
            "claim": "Revenue grew last quarter",
            "query": "revenue growth",
            "session_id": "validate",
            "truth_score": 0.55,
            "risk_analysis": {"risk_score": 0.3},
            "title": "t",
            "evidence": [],
            "sources": [],
            "key_findings": [],
            "citations": [],
            "lie_detection": {"result": {"deception_score": 0.2}, "confidence": 0.6},
            "fact_checking": {"result": {"support_score": 0.5}, "confidence": 0.6},
            "news_verification": {"confidence": 0.5},
            "source_credibility": {"result": {"average_credibility": 0.5}, "confidence": 0.5},
            "turn": {"note": "x"},
        }
        oks = []
        for a in agents:
            r = requests.post(
                f"{API}/api/v1/veridiq/agents/{a['agent_type']}/run",
                json={"payload": sample},
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            assert body.get("ok") is True
            oks.append(a["agent_type"])
        return {"ran": len(oks), "agents": oks}

    results.append(check("all_agents_api", each_agent_api))

    results.append(
        check(
            "rag_status",
            lambda: (
                lambda d: d if d.get("rag") else (_ for _ in ()).throw(AssertionError("no rag"))
            )(requests.get(f"{API}/api/v1/veridiq/system", timeout=10).json()),
        )
    )

    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frontend": UI,
        "backend": API,
        "docs": f"{API}/docs",
        "passed": passed,
        "total": len(results),
        "ok": passed == len(results),
        "results": results,
        "failed": failed,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "passed": passed, "total": len(results), "report": str(REPORT)}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
