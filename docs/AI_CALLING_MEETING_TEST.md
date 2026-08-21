# Test a live meeting on AI Calling

## What was wrong
The Calling page showed **static agent avatar images** only. No agent joined the LiveKit room as a remote participant, and no TTS audio was published — so it never felt like a human on the other side. Schedule/timed-budget UI was also easy to miss.

## What to do (happy path)

1. Ensure API is running on `:8002` with LiveKit env set:
   - `VERIDIQ_LIVEKIT_URL`
   - `VERIDIQ_LIVEKIT_API_KEY`
   - `VERIDIQ_LIVEKIT_API_SECRET`
2. Open the frontend → **AI Calling** (`/dashboard/calling`).
3. You should see **LiveKit configured** and a remaining **Budget** pill (default max **120s**/call).
4. Click **Meet Marcus now** (or schedule a PKT time, then **Call / Start live** when the window opens).
5. The page admits you, connects LiveKit, and Marcus joins as a **remote participant** with an avatar video tile + spoken greeting (edge-tts).
6. Confirm you hear audio and see the agent tile (not only your self-view). Leave/End when done — timed budget auto-expires via the calling worker.

## If LiveKit is not configured
The lobby still loads. Schedule + timed sessions remain visible. A clear banner explains which env vars to set; live join is blocked until credentials exist.

## Useful API checks
```bash
curl -s http://127.0.0.1:8002/api/v1/health
curl -s http://127.0.0.1:8002/api/v1/veridiq/agents/pipeline/health
curl -s http://127.0.0.1:8002/api/v1/veridiq/calling/budget
curl -s http://127.0.0.1:8002/api/v1/veridiq/calling/timed
curl -s -X POST http://127.0.0.1:8002/api/v1/veridiq/calling/meetings/quick -H "Content-Type: application/json" -d "{\"topic\":\"Test with Marcus\"}"
```

Diagnose script:
```bash
python scripts/diagnose_agent_pipeline.py --base http://127.0.0.1:8002
```
