"""AI Calling command agent — Call connects you to Marcus; natural-language
commands trigger real marketing / influencer / workforce actions.

This is NOT a Twilio dialer. Phone campaigns remain available under the legacy
``/api/v1/veridiq/calling/campaigns`` routes; the Calling page UX is an
in-app agent session that uses ``ai_gateway`` to understand commands and
executes honest backend actions (no fabricated success).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from veridiq.workforce.identities import identity_for

AGENT_TYPE = "ai_calling"

# Navigation hints surfaced to the frontend after successful actions.
LINK_LIVE_RUNTIME = "/dashboard/runtime"
LINK_MARKETING = "/dashboard/marketing"
LINK_COMMS = "/dashboard/comms"

_VALID_INTENTS = frozenset(
    {
        "run_marketing",
        "run_influencer",
        "influencer_research",
        "deep_research",
        "request_personal_meeting",
        "schedule_timed_call",
        "help",
        "chat",
    }
)

_SYSTEM_PROMPT = """You are Marcus, VERIDIQ's AI Calling Coordinator — an in-app command agent
and a capable general AI assistant. Answer any topic fully when intent=chat.
The user is speaking to you after pressing Call. Parse their message into ONE JSON object only
(no markdown, no prose outside JSON) with this shape:
{"intent":"<one of: run_marketing|run_influencer|influencer_research|deep_research|request_personal_meeting|schedule_timed_call|help|chat>",
 "query":"<optional search query OR specialist name/topic for personal meeting>",
 "niche":"<optional niche>",
 "reply":"<spoken reply confirming an action, answering help, OR a full clear answer for chat>"}

Intent guide:
- run_marketing: start / run marketing agencies / marketing team / "run marketing" / market VeriDiQ
- run_influencer: run influencer agent / command influencer / Adrian / influencer campaign drafts
- influencer_research: research creators / find influencers / influencer research (extract query)
- deep_research: deep research / find out / look up / "nikaal do" / extract facts from the web
  on ANY topic (not influencer-specific). Put the topic in "query".
- request_personal_meeting: arrange / book / set up a personal meeting with a specialist
  (Canva, daily posts, Lena, Jasper, content, social poster, etc.). Put specialist in "query".
- schedule_timed_call: schedule / start a timed voice call window (2-minute budget)
- help: what can you do / commands / capabilities
- chat: greetings OR general knowledge on ANY topic (science, tech, blockchain, history,
  definitions, how-tos) that is not an action intent above

For intent=chat: answer fully and clearly in "reply".
Do NOT force every answer into a VERIDIQ pitch. VERIDIQ product help is optional when relevant.
When they ask about VERIDIQ / marketing / agents / verification, use product context and suggest
real commands when useful.
Do not compare yourself to other AI products or brand yourself as one.
Never say you can "talk like ChatGPT", "are like ChatGPT", or similar self-branding.

Be honest: you trigger real backend runs; you do not dial phones or invent live posts/API secrets
or fabricate research sources. No criminal assistance.
"""

_CHAT_SYSTEM_PROMPT = """You are Marcus, a capable general AI assistant inside VERIDIQ.
Answer ANY user question fully and clearly — science, tech, blockchain, history, definitions,
how-tos, comparisons, examples. Do not force answers into a VERIDIQ pitch; product help is
optional only when they ask about VERIDIQ or platform actions.
You can also run marketing / influencer / deep-research web tasks when they request those actions.
Do not compare yourself to other AI products or brand yourself as one.
Never say you can "talk like ChatGPT", "are like ChatGPT", or similar self-branding.
Safety: no criminal assistance; do not invent live API secrets, fake posts, or fabricated sources.
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def agent_persona() -> dict[str, Any]:
    ident = identity_for(AGENT_TYPE)
    return {
        "agent_type": AGENT_TYPE,
        "name": ident.get("name") or "Marcus",
        "role": ident.get("role") or "AI Calling Coordinator",
        "specialty": ident.get("specialty") or "Natural-language command agent for marketing and influencer runs",
        "skills": ident.get("skills") or [],
        "avatar_hue": ident.get("avatar_hue", 18),
        "greeting": (
            f"Hi — I'm {ident.get('name') or 'Marcus'}. Ask me anything, run marketing/influencer, "
            "or say “arrange a personal meeting with the Canva / daily posts agent” — "
            "I'll post in Collaboration Hub for approval, then you accept the invite to join LiveKit."
        ),
    }


def _keyword_intent(message: str) -> dict[str, Any]:
    """Deterministic fallback when no LLM key is configured."""
    q = (message or "").strip().lower()
    if not q:
        return {
            "intent": "help",
            "query": "",
            "niche": "",
            "reply": "Say a command — for example: run marketing agencies, or command influencer.",
        }

    # Marketing team
    marketing_markers = (
        "marketing",
        "market agency",
        "agencies",
        "run marketing",
        "start marketing",
        "marketing team",
        "run now",
        "daily pack",
        "content pack",
    )
    if any(m in q for m in marketing_markers) and "influencer" not in q:
        return {
            "intent": "run_marketing",
            "query": "",
            "niche": "",
            "reply": "Starting the marketing team on the default campaign now.",
        }

    # Influencer research vs run
    research_markers = ("research", "find", "search", "look up", "lookup", "discover", "shortlist")
    if "influencer" in q or "creator" in q or "adrian" in q:
        if any(m in q for m in research_markers):
            # Strip common command words to leave a query
            query = re.sub(
                r"\b(research|find|search|look\s*up|lookup|discover|shortlist|influencer|influencers|creators?|please|command)\b",
                " ",
                q,
                flags=re.I,
            )
            query = re.sub(r"\s+", " ", query).strip() or "AI verification creators"
            return {
                "intent": "influencer_research",
                "query": query,
                "niche": "",
                "reply": f"Researching creators for “{query}”.",
            }
        return {
            "intent": "run_influencer",
            "query": "",
            "niche": "",
            "reply": "Running Adrian (influencer relations) on the default campaign.",
        }

    # Personal meeting with specialist via Collaboration Hub
    from veridiq.calling.live_threads import extract_meeting_request

    meeting_req = extract_meeting_request(message)
    if meeting_req:
        return {
            "intent": "request_personal_meeting",
            "query": meeting_req.get("specialist_query") or q,
            "niche": "",
            "reply": "I'll post a personal-meeting request in the Collaboration Hub for the specialist to approve.",
        }

    # Timed voice call window (budget-enforced)
    timed_markers = (
        "timed call",
        "schedule call",
        "schedule a call",
        "start a timed",
        "2 minute call",
        "2-minute call",
        "two minute call",
        "call budget",
        "voice call window",
    )
    if any(m in q for m in timed_markers):
        return {
            "intent": "schedule_timed_call",
            "query": "",
            "niche": "",
            "reply": "Scheduling a timed voice-call window within today's calling budget.",
        }

    # General deep research (any topic) — English + Roman-Urdu task phrasing
    from veridiq.research.deep_research import extract_research_query, looks_like_research_task

    if looks_like_research_task(message):
        query = extract_research_query(message) or (message or "").strip()
        return {
            "intent": "deep_research",
            "query": query,
            "niche": "",
            "reply": f"Running deep research on “{query}”.",
        }

    if any(w in q for w in ("help", "what can", "commands", "capabilities", "what do you")):
        return {
            "intent": "help",
            "query": "",
            "niche": "",
            "reply": (
                "I can: (1) answer general questions, (2) deep web research, "
                "(3) run marketing agencies, (4) influencer runs/research, "
                "(5) arrange a personal LiveKit meeting with a specialist (Canva/daily posts) "
                "via Collaboration Hub invite, (6) schedule a timed voice call within the daily budget."
            ),
        }

    if any(w in q for w in ("hi", "hello", "hey", "namaste", "hola")):
        return {
            "intent": "chat",
            "query": "",
            "niche": "",
            "reply": agent_persona()["greeting"],
        }

    return {
        "intent": "chat",
        "query": "",
        "niche": "",
        "reply": (
            "Ask me anything (general knowledge), or try “deep research <topic>”, "
            "“run marketing agencies”, “command influencer”, or "
            "“research influencers in AI verification”."
        ),
    }


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    # Strip optional markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def parse_intent(message: str) -> dict[str, Any]:
    """Use ai_gateway when configured; otherwise keyword fallback. Always returns a valid intent dict."""
    fallback = _keyword_intent(message)
    try:
        from veridiq.integrations import ai_gateway

        st = ai_gateway.status()
        if not st.get("configured"):
            return {**fallback, "parser": "keywords", "llm": {"configured": False, "message": st.get("message")}}

        prompt = (
            f"{_SYSTEM_PROMPT}\n\nUser message:\n{(message or '').strip()[:1500]}\n\nJSON:"
        )
        gen = ai_gateway.generate(prompt=prompt, task_type="fast", max_providers=3, max_tokens=1200)
        if not gen.get("ok"):
            return {
                **fallback,
                "parser": "keywords",
                "llm": {
                    "configured": True,
                    "ok": False,
                    "status": gen.get("status"),
                    "message": gen.get("message"),
                    "provider_used": gen.get("provider_used"),
                },
            }

        parsed = _extract_json_object(str(gen.get("text") or ""))
        if not parsed:
            return {
                **fallback,
                "parser": "keywords",
                "llm": {
                    "configured": True,
                    "ok": True,
                    "status": "parse_failed",
                    "message": "LLM replied but JSON intent could not be parsed; used keyword fallback.",
                    "provider_used": gen.get("provider_used"),
                    "raw": str(gen.get("text") or "")[:400],
                },
            }

        intent = str(parsed.get("intent") or "chat").strip().lower()
        if intent not in _VALID_INTENTS:
            intent = fallback["intent"]
        reply_limit = 4000 if intent in ("chat", "deep_research") else 800
        reply = str(parsed.get("reply") or fallback["reply"]).strip()[:reply_limit]
        query = str(parsed.get("query") or "").strip()[:200]
        niche = str(parsed.get("niche") or "").strip()[:120]
        # If LLM picked research without a query, salvage from keywords
        if intent == "influencer_research" and not query:
            query = fallback.get("query") or "AI verification creators"
        if intent == "deep_research" and not query:
            query = fallback.get("query") or (message or "").strip()[:200]

        return {
            "intent": intent,
            "query": query,
            "niche": niche,
            "reply": reply or fallback["reply"],
            "parser": "llm",
            "llm": {
                "configured": True,
                "ok": True,
                "status": "ok",
                "provider_used": gen.get("provider_used"),
                "model": gen.get("model"),
            },
        }
    except Exception as exc:
        return {
            **fallback,
            "parser": "keywords",
            "llm": {"configured": False, "ok": False, "message": str(exc)[:200]},
        }


def _execute_run_marketing() -> dict[str, Any]:
    """Same coordinated team start as POST /api/v1/veridiq/marketing/run-now."""
    from veridiq.agents import get_agent
    from veridiq.marketing import build_run_payload, get_or_create_default_campaign
    from veridiq.workforce import control as agent_control
    from veridiq.workforce.departments import DEPARTMENTS
    from veridiq.workforce.pool import global_worker_pool

    campaign = get_or_create_default_campaign()
    agent_types = DEPARTMENTS["marketing_agency"]["agents"]
    team_run_id = f"team-{uuid.uuid4().hex[:12]}"
    sample_payload = build_run_payload(agent_types[0], campaign["campaign_id"], team_run=True, team_run_id=team_run_id)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    min_visible = global_worker_pool.marketing_min_visible_sec()
    for agent_type in agent_types:
        try:
            agent_control.assert_runnable(agent_type)
        except agent_control.AgentStoppedError as exc:
            skipped.append({"agent_type": agent_type, "reason": f"agent is {exc.status}"})
            continue
        agent = get_agent(agent_type)
        run_job_id = f"agent-run-{uuid.uuid4().hex[:12]}"
        run_payload = build_run_payload(agent_type, campaign["campaign_id"], team_run=True, team_run_id=team_run_id)

        def _fn(agent=agent, run_job_id=run_job_id, run_payload=run_payload):
            return agent.run(run_payload, job_id=run_job_id)

        channel_hint = (run_payload.get("channels") or ["content"])[0]
        result = global_worker_pool.start_agent_task(
            agent_type=agent_type,
            fn=_fn,
            job_id=run_job_id,
            task=f"Marketing team run — drafting {channel_hint} content ({agent_type})",
            min_visible_sec=min_visible,
            platform=channel_hint,
            channel=channel_hint,
        )
        started.append({"agent_type": agent_type, **result})

    message = f"Started {len(started)}/{len(agent_types)} marketing agent(s) on '{campaign['name']}'."
    if skipped:
        message += f" {len(skipped)} skipped (stopped/paused)."
    if sample_payload.get("skip_draft_generation"):
        message += f" {sample_payload.get('skip_reason')}"
    else:
        message += " Coordinated run — capped new drafts (manager pack + one per specialist)."

    return {
        "ok": True,
        "action": "run_marketing",
        "status": "started" if started else "skipped",
        "message": message,
        "campaign_id": campaign["campaign_id"],
        "campaign_name": campaign["name"],
        "team_run_id": team_run_id,
        "started": started,
        "skipped": skipped,
        "links": [
            {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
            {"label": "Marketing Agency", "href": LINK_MARKETING},
        ],
    }


def _execute_run_influencer() -> dict[str, Any]:
    """Start influencer_relations agent against the default campaign (real drafts)."""
    from veridiq.agents import get_agent
    from veridiq.marketing import build_run_payload, get_or_create_default_campaign
    from veridiq.workforce import control as agent_control
    from veridiq.workforce.pool import global_worker_pool

    campaign = get_or_create_default_campaign()
    agent_type = "influencer_relations"
    try:
        agent_control.assert_runnable(agent_type)
    except agent_control.AgentStoppedError as exc:
        return {
            "ok": False,
            "action": "run_influencer",
            "status": "skipped",
            "message": f"Influencer agent is {exc.status} — start it from Marketing Agency or control, then retry.",
            "links": [
                {"label": "Marketing Agency", "href": LINK_MARKETING},
                {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
            ],
        }

    agent = get_agent(agent_type)
    run_job_id = f"agent-run-{uuid.uuid4().hex[:12]}"
    team_run_id = f"infl-{uuid.uuid4().hex[:10]}"
    # Individual influencer command (not full team) — bounded agent run + queue auto-clear + postings handoff.
    run_payload = build_run_payload(
        agent_type, campaign["campaign_id"], team_run=False, team_run_id=team_run_id, auto_clear_queue=True
    )
    run_payload["handoff_to_postings"] = True
    min_visible = global_worker_pool.marketing_min_visible_sec()

    def _fn():
        return agent.run(run_payload, job_id=run_job_id)

    channel_hint = (run_payload.get("channels") or ["instagram"])[0]
    result = global_worker_pool.start_agent_task(
        agent_type=agent_type,
        fn=_fn,
        job_id=run_job_id,
        task=f"Influencer command — drafting {channel_hint} content (Adrian)",
        min_visible_sec=min_visible,
        platform=channel_hint,
        channel=channel_hint,
    )
    skip_note = ""
    if run_payload.get("queue_prepared") and run_payload["queue_prepared"].get("cleared"):
        skip_note = f" Cleared {run_payload['queue_prepared']['cleared']} old draft(s) so new work could queue."
    return {
        "ok": True,
        "action": "run_influencer",
        "status": result.get("status") or "started",
        "message": (
            f"Adrian (influencer relations) started on '{campaign['name']}'. "
            "Drafts land in the marketing queue; captions also hand off toward Postings."
            + skip_note
        ),
        "campaign_id": campaign["campaign_id"],
        "campaign_name": campaign["name"],
        "team_run_id": team_run_id,
        "started": [{"agent_type": agent_type, **result}],
        "links": [
            {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
            {"label": "Marketing Agency", "href": LINK_MARKETING},
            {"label": "Postings Studio", "href": "/dashboard/postings"},
        ],
    }


def _execute_influencer_research(*, query: str, niche: str = "") -> dict[str, Any]:
    from veridiq.influencer.research import research_creators

    research = research_creators(query=query or "AI verification creators", niche=niche or None, max_results=8, summarize=True)
    ok = bool(research.get("ok") or research.get("count"))
    status = research.get("status") or ("ok" if ok else "empty")
    return {
        "ok": ok or status == "ok",
        "action": "influencer_research",
        "status": status,
        "message": research.get("message") or (
            f"Found {research.get('count', 0)} public hit(s)." if research.get("count") else "No public hits (check search API keys)."
        ),
        "research": {
            "count": research.get("count"),
            "summary": research.get("summary"),
            "results": (research.get("results") or [])[:8],
            "providers_used": research.get("providers_used"),
            "status": research.get("status"),
        },
        "links": [
            {"label": "Marketing Agency", "href": LINK_MARKETING},
            {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
        ],
    }


def _execute_deep_research(*, query: str) -> dict[str, Any]:
    from veridiq.research.deep_research import deep_research, format_research_answer

    research = deep_research(query=query or "", max_results=8, summarize=True)
    status = research.get("status") or "error"
    ok = bool(research.get("ok")) or status == "configuration_required"
    return {
        "ok": ok,
        "action": "deep_research",
        "status": status,
        "message": format_research_answer(research),
        "research": {
            "count": research.get("count"),
            "summary": research.get("summary"),
            "results": (research.get("results") or [])[:8],
            "providers_used": research.get("providers_used"),
            "status": research.get("status"),
            "query": research.get("query"),
        },
        "links": [],
    }


def _execute_request_personal_meeting(*, query: str) -> dict[str, Any]:
    from veridiq.calling.live_threads import request_personal_meeting

    result = request_personal_meeting(specialist_query=query or "canva daily posts", topic=query or None)
    return {
        "ok": bool(result.get("ok")),
        "action": "request_personal_meeting",
        "status": "ok" if result.get("ok") else "error",
        "message": result.get("message") or "Posted personal meeting request.",
        "specialist": result.get("specialist"),
        "invite": result.get("invite"),
        "thread": result.get("thread"),
        "links": result.get("links")
        or [
            {"label": "Collaboration Hub", "href": "/dashboard/collaboration"},
            {"label": "AI Calling", "href": "/dashboard/calling"},
        ],
    }


def _execute_schedule_timed_call(*, purpose: str = "") -> dict[str, Any]:
    from veridiq.calling.timed_calls import schedule_timed_call, start_session

    scheduled = schedule_timed_call(
        purpose=purpose or "Marcus timed calling window",
        agent_type=AGENT_TYPE,
        user_key="default",
        record_chain=True,
    )
    if not scheduled.get("ok"):
        return {
            "ok": False,
            "action": "schedule_timed_call",
            "status": scheduled.get("status") or "error",
            "message": scheduled.get("message") or "Could not schedule timed call.",
            "budget": scheduled.get("budget"),
            "links": [{"label": "AI Calling", "href": "/dashboard/calling"}],
        }
    sid = (scheduled.get("session") or {}).get("session_id")
    started = start_session(sid) if sid else None
    return {
        "ok": True,
        "action": "schedule_timed_call",
        "status": "active" if (started or {}).get("ok") else "scheduled",
        "message": (
            f"{scheduled.get('message')} "
            + ((started or {}).get("message") or "")
        ).strip(),
        "session": (started or {}).get("session") or scheduled.get("session"),
        "budget": scheduled.get("budget"),
        "chain": scheduled.get("chain"),
        "links": [
            {"label": "AI Calling", "href": "/dashboard/calling"},
            {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
        ],
    }


def handle_command(message: str, *, history: Optional[list[dict[str, str]]] = None) -> dict[str, Any]:
    """Parse a natural-language command and execute the matching real action."""
    _ = history  # reserved for multi-turn context later
    persona = agent_persona()
    text = (message or "").strip()
    if not text:
        return {
            "ok": True,
            "agent": persona,
            "intent": "help",
            "reply": persona["greeting"],
            "action": None,
            "links": [],
            "timestamp": _utc_now(),
        }

    parsed = parse_intent(text)
    intent = parsed["intent"]
    reply = parsed["reply"]
    action_result: Optional[dict[str, Any]] = None

    if intent == "run_marketing":
        action_result = _execute_run_marketing()
        reply = f"{reply} {action_result.get('message', '')}".strip()
    elif intent == "run_influencer":
        action_result = _execute_run_influencer()
        reply = f"{reply} {action_result.get('message', '')}".strip()
    elif intent == "influencer_research":
        action_result = _execute_influencer_research(query=parsed.get("query") or "", niche=parsed.get("niche") or "")
        summary = (action_result.get("research") or {}).get("summary")
        if summary:
            reply = f"{reply}\n\n{summary}".strip()
        else:
            reply = f"{reply} {action_result.get('message', '')}".strip()
    elif intent == "deep_research":
        action_result = _execute_deep_research(query=parsed.get("query") or text)
        research_body = action_result.get("message") or ""
        summary = (action_result.get("research") or {}).get("summary")
        reply = (summary or research_body or reply).strip()
    elif intent == "request_personal_meeting":
        action_result = _execute_request_personal_meeting(query=parsed.get("query") or text)
        reply = f"{reply} {action_result.get('message', '')}".strip()
    elif intent == "schedule_timed_call":
        action_result = _execute_schedule_timed_call(purpose=parsed.get("query") or text)
        reply = f"{reply} {action_result.get('message', '')}".strip()
    elif intent == "help":
        action_result = {
            "ok": True,
            "action": "help",
            "status": "ok",
            "message": reply,
            "links": [
                {"label": "Live Agent Runtime", "href": LINK_LIVE_RUNTIME},
                {"label": "Marketing Agency", "href": LINK_MARKETING},
                {"label": "Collaboration Hub", "href": "/dashboard/collaboration"},
            ],
        }
    else:
        # chat — optional LLM enrich when keywords already answered
        action_result = {
            "ok": True,
            "action": "chat",
            "status": "ok",
            "message": reply,
            "links": [],
        }
        # If LLM was used and gave a richer reply, keep it; else try a short generate for chat
        if parsed.get("parser") == "keywords":
            try:
                from veridiq.integrations import ai_gateway

                if ai_gateway.status().get("configured"):
                    gen = ai_gateway.generate(
                        prompt=(
                            f"{_CHAT_SYSTEM_PROMPT}\n\nUser said:\n{text[:1500]}\n\nAssistant:"
                        ),
                        task_type="reason",
                        max_providers=3,
                        max_tokens=900,
                    )
                    if gen.get("ok") and gen.get("text"):
                        reply = str(gen.get("text")).strip()[:4000]
                        action_result["message"] = reply
                        parsed["llm"] = {
                            "configured": True,
                            "ok": True,
                            "provider_used": gen.get("provider_used"),
                            "status": "ok",
                        }
                        parsed["parser"] = "llm_chat"
            except Exception:
                pass

    links = (action_result or {}).get("links") or []
    return {
        "ok": bool((action_result or {}).get("ok", True)),
        "agent": persona,
        "intent": intent,
        "reply": reply,
        "parser": parsed.get("parser"),
        "llm": parsed.get("llm"),
        "action": action_result,
        "links": links,
        "timestamp": _utc_now(),
    }
