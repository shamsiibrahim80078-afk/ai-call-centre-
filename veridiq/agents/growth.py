"""Growth specialist agents — AI Calling, LinkedIn outreach, Sales intelligence.

These agents never fabricate outbound activity. Each reports real integration
configuration state and only prepares drafts/campaigns that require explicit
human approval before any external contact is made.
"""

from __future__ import annotations

from typing import Any

from veridiq.agents.base import VeridiqAgent


class AICallingAgent(VeridiqAgent):
    agent_type = "ai_calling"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.calling import budget as calling_budget
        from veridiq.calling.campaigns import list_campaigns
        from veridiq.calling.timed_calls import list_sessions, schedule_timed_call, start_session
        from veridiq.calling.worker import worker_status
        from veridiq.integrations import twilio_calling

        action = str(payload.get("action") or "status").strip().lower()
        user_key = str(payload.get("user_key") or "default")
        budget = calling_budget.budget_status(agent_type=self.agent_type, user_key=user_key)
        status = twilio_calling.status()
        campaigns = list_campaigns()
        queued = [c for c in campaigns if c["status"] == "queued_for_approval"]
        dialed = [c for c in campaigns if c["status"] == "dialed"]
        timed = list_sessions(agent_type=self.agent_type, user_key=user_key, limit=10)
        worker = worker_status()

        timed_result = None
        if action in {"schedule", "schedule_timed_call", "timed_call"}:
            timed_result = schedule_timed_call(
                purpose=str(payload.get("purpose") or payload.get("text") or "Timed AI calling session"),
                script=str(payload.get("script") or ""),
                to_number=str(payload.get("to_number") or ""),
                requested_seconds=payload.get("requested_seconds") or payload.get("max_seconds"),
                agent_type=self.agent_type,
                user_key=user_key,
                record_chain=payload.get("record_chain", True) is not False,
            )
            if timed_result.get("ok") and payload.get("auto_start") is True:
                sid = (timed_result.get("session") or {}).get("session_id")
                if sid:
                    timed_result["start"] = start_session(sid)
            budget = calling_budget.budget_status(agent_type=self.agent_type, user_key=user_key)

        summary_bits = [
            f"Timed budget: {budget['consumed_seconds']:.0f}/{budget['daily_budget_seconds']:.0f}s used today "
            f"(per-call max {budget['per_call_max_seconds']:.0f}s).",
            f"Twilio Voice is {status['status']}.",
            f"{len(queued)} Twilio campaign(s) awaiting approval, {len(dialed)} dialed.",
            f"Worker {'running' if worker.get('thread_alive') else 'idle'}.",
        ]
        if timed_result:
            summary_bits.insert(0, timed_result.get("message") or f"Timed call action={action}.")

        return {
            "summary": " ".join(summary_bits),
            "evidence": [
                {"campaign_id": c["campaign_id"], "to_number": c["to_number"], "status": c["status"]}
                for c in campaigns[:10]
            ],
            "sources": ["Twilio Voice REST API (official)"] if status["configured"] else [],
            "risks": [
                "No live Twilio dial without explicit campaign approval.",
                "Timed sessions enforce VERIDIQ_CALLING_MAX_SECONDS and VERIDIQ_CALLING_DAILY_BUDGET_SECONDS.",
            ],
            "status": status["status"],
            "integration": status,
            "budget": budget,
            "timed_sessions": timed,
            "timed_result": timed_result,
            "worker": worker,
            "disclaimer": (
                "Timed call windows are budget-enforced asynchronously. "
                "LiveKit meetings remain separate; Twilio dials still require approval."
            ),
            "confidence": 0.7 if budget.get("can_start_call") else 0.45,
        }


class LinkedInOutreachAgent(VeridiqAgent):
    agent_type = "linkedin_outreach"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.integrations import linkedin

        status = linkedin.status()
        context = str(payload.get("text") or payload.get("context") or "").strip()
        draft = None
        if context:
            from veridiq.comms import draft_communication

            draft = draft_communication(kind="outreach", context=context, recipient_hint=payload.get("recipient_hint", ""))
        return {
            "summary": (
                f"LinkedIn OAuth is {status['status']}."
                + (
                    " Outreach draft prepared — POST /api/v1/veridiq/comms/approve with "
                    "channel=linkedin to publish it via the official UGC Posts API."
                    if draft
                    else ""
                )
            ),
            "evidence": [{"draft_id": draft["draft_id"], "subject": draft["subject"]}] if draft else [],
            "sources": ["LinkedIn official API (OAuth 2.0, UGC Posts)"] if status["configured"] else [],
            "risks": ["No post or message is ever sent without explicit approval and a live access token."],
            "status": status["status"],
            "integration": status,
            "draft": draft,
            "disclaimer": "Outreach readiness only — official API required for any live action.",
            "confidence": 0.6 if status["configured"] else 0.3,
        }


class SalesIntelligenceAgent(VeridiqAgent):
    agent_type = "sales_intelligence"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.integrations import crm, email_smtp

        crm_status = crm.status()
        email_status = email_smtp.status()
        deal_context = str(payload.get("text") or payload.get("context") or "").strip()
        return {
            "summary": (
                f"CRM is {crm_status['status']}; email outreach is {email_status['status']}."
                + (" Deal context reviewed." if deal_context else "")
            ),
            "evidence": [{"note": "CRM lookups only run when credentials are configured."}],
            "sources": ["HubSpot/generic CRM API"] if crm_status["configured"] else [],
            "risks": ["Contact/deal data is never fabricated — CRM lookups require configured credentials."],
            "status": "ready" if (crm_status["configured"] or email_status["configured"]) else "configuration_required",
            "integrations": {"crm": crm_status, "email": email_status},
            "disclaimer": "Pipeline readiness report only — no deal data invented.",
            "confidence": 0.6 if crm_status["configured"] else 0.35,
        }


GROWTH_AGENT_CLASSES: dict[str, type[VeridiqAgent]] = {
    "ai_calling": AICallingAgent,
    "linkedin_outreach": LinkedInOutreachAgent,
    "sales_intelligence": SalesIntelligenceAgent,
}
