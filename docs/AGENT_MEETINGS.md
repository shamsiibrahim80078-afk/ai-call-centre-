# Agent↔agent meetings — how to test

## What this is

Agents schedule and join **each other** on LiveKit. You are optional — **Watch live** as a subscribe-only spectator (mic/cam off by default). Marcus (Call Organizer) posts the fixed join time after approval; a countdown runs, then agents auto-join and run a short turn-taking TTS dialogue.

## Env (defaults)

```bash
VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS=120   # wait after approve before agents join
VERIDIQ_AGENT_MEET_DURATION_SECONDS=120    # initial call budget
VERIDIQ_AGENT_MEET_EXTENDED_SECONDS=300    # after mid-call invite
VERIDIQ_LIVEKIT_URL=...
VERIDIQ_LIVEKIT_API_KEY=...
VERIDIQ_LIVEKIT_API_SECRET=...
```

For a fast local demo, set countdown to 10 seconds:

```bash
VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS=10
```

## Manual UI flow

1. Open **Collaboration Hub** (`/dashboard/collaboration`).
2. In compose, send something like: `I need to schedule a meeting with you` (Twitter/marketing → influencer pair is inferred).
3. Click **Approve** on the agent-meeting card (or compose `approved, let's meet`).
4. Marcus posts the join time; the card shows a **countdown**.
5. When status is `live` (or after countdown), click **Watch live** → AI Calling opens in spectator mode.
6. Mid-call sidebar: invite another agent type → budget extends to **300s**.

Optional: `go join this meeting: https://meet.google.com/...` starts the external Meet proxy (best-effort Playwright + Marcus LiveKit narration; Meet often blocks bots).

## API smoke (PowerShell)

```powershell
# Propose
Invoke-RestMethod -Method POST http://127.0.0.1:8002/api/v1/veridiq/calling/agent-meetings/propose `
  -ContentType application/json `
  -Body '{"proposer_agent":"x_twitter_voice","invitee_agent":"influencer_relations","topic":"Demo sync","countdown":10}'

# Approve (use proposal_id from above)
Invoke-RestMethod -Method POST http://127.0.0.1:8002/api/v1/veridiq/calling/agent-meetings/<proposal_id>/approve

# After countdown — or force for tests
Invoke-RestMethod -Method POST "http://127.0.0.1:8002/api/v1/veridiq/calling/agent-meetings/<proposal_id>/start?force=true"

# Spectator token
Invoke-RestMethod -Method POST http://127.0.0.1:8002/api/v1/veridiq/calling/agent-meetings/<proposal_id>/spectator
```

## Unit tests

```bash
pytest tests/test_agent_meetings.py -q
```

## Architecture (short)

| Piece | Role |
|-------|------|
| `veridiq/calling/agent_meetings.py` | propose → approve → countdown → live; dialogue TTS; invite/extend |
| `veridiq/calling/spectator.py` | subscribe-only LiveKit JWT |
| `veridiq/calling/external_meet.py` | URL job + Playwright best-effort + Marcus narration |
| Calling worker | ticks approved→live when `start_at` elapses |
| Collaboration Hub | schedule/approve intents + proposal cards |
| AI Calling / LiveKitMeetingRoom | spectator mode, multi-agent dialogue, invite sidebar |
