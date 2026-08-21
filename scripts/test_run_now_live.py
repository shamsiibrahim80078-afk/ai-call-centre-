"""Quick live HTTP proof: run-now → marketing/team shows Working > 0."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8001"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def post(path: str) -> dict:
    req = urllib.request.Request(
        BASE + path,
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


print("=== BEFORE run-now ===")
team = get("/api/v1/veridiq/marketing/team")
print("active_workers:", team["workforce"]["active_workers"])
print("working cards:", sum(1 for c in team["cards"] if c["status"] == "working"))

print("\n=== POST run-now ===")
run = post("/api/v1/veridiq/marketing/run-now")
print("message:", run.get("message"))
print("started:", len(run.get("started", [])), "min_visible:", run.get("min_visible_sec"))

for delay_ms in [100, 200, 300, 500, 1000, 2000]:
    time.sleep(delay_ms / 1000)
    team = get("/api/v1/veridiq/marketing/team")
    wf = get("/api/v1/veridiq/workforce")
    working = sum(1 for c in team["cards"] if c["status"] == "working")
    print(
        f"  +{delay_ms}ms: team.active={team['workforce']['active_workers']} "
        f"working_cards={working} workforce.active={wf['active_workers']}"
    )
    if working > 0:
        for c in [x for x in team["cards"] if x["status"] == "working"][:3]:
            print(f"    {c['agent_type']}: {c['status_label']} | {c['current_task']}")

print("\n=== go-live-checklist ===")
gl = get("/api/v1/veridiq/marketing/go-live-checklist")
print("ready:", gl.get("ready_count"), "/", gl.get("total"))
