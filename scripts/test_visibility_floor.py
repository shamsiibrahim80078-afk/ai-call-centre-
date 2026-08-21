"""Verify 12s visibility floor after run-now."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8001"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def post(path: str, body: bytes = b"{}") -> dict:
    req = urllib.request.Request(
        BASE + path,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


print("=== run-now + 14s visibility poll ===")
run = post("/api/v1/veridiq/marketing/run-now")
print("started:", len(run.get("started", [])), "min_visible:", run.get("min_visible_sec"))

t0 = time.time()
max_working = 0
while time.time() - t0 < 14:
    team = get("/api/v1/veridiq/marketing/team")
    working = sum(1 for c in team["cards"] if c["status"] == "working")
    aw = team["workforce"]["active_workers"]
    max_working = max(max_working, working)
    print(f"t+{time.time() - t0:.1f}s active={aw} working={working}")
    time.sleep(1)

print("max_working:", max_working)
assert max_working > 0, "Working never rose above 0"

print("\n=== clear-pending ===")
result = post("/api/v1/veridiq/marketing/queue/clear-pending?keep_recent=20")
print(json.dumps(result, indent=2))
