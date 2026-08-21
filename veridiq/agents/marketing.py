"""Marketing Agency agents — Marketing Manager, Content Creator, Social

Poster, Telegram Community, X/Twitter Voice, Influencer Relations.



Every agent here reports real integration/campaign state and only ever

queues comms drafts (draft -> approve -> send gate) — none of them send an

external message directly. See `veridiq/marketing/` for the shared

campaign/content logic these agents call into.

"""



from __future__ import annotations



from typing import Any



from veridiq.agents.base import VeridiqAgent





def _pack_kwargs(payload: dict[str, Any], *, created_by_agent: str) -> dict[str, Any]:

    return {

        "channels": payload.get("channels"),

        "features": payload.get("features"),

        "created_by_agent": created_by_agent,

        "max_drafts": payload.get("max_drafts"),

        "skip_draft_generation": bool(payload.get("skip_draft_generation")),

        "skip_reason": payload.get("skip_reason"),

    }





class MarketingManagerAgent(VeridiqAgent):

    agent_type = "marketing_manager"



    def process(self, payload: dict[str, Any]) -> dict[str, Any]:

        from veridiq.marketing.campaigns import daily_status, generate_daily_pack, get_or_create_default_campaign, list_campaigns



        campaign_id = payload.get("campaign_id") or get_or_create_default_campaign()["campaign_id"]

        result = generate_daily_pack(campaign_id, **_pack_kwargs(payload, created_by_agent=self.agent_type))

        campaigns = list_campaigns()

        active = [c for c in campaigns if c["status"] == "active"]

        today = daily_status(campaign_id=campaign_id)

        summary = (

            f"Orchestrated daily pack: {result.get('count', 0)} draft(s) queued. "

            f"{len(active)} active campaign(s). {today['pending_approval']} awaiting approval today."

        )

        if result.get("skipped"):

            summary = result.get("message") or summary

        return {

            "summary": summary,

            "result": result,

            "campaigns": [

                {"campaign_id": c["campaign_id"], "name": c["name"], "status": c["status"], "channels": c["channels"]}

                for c in campaigns[:10]

            ],

            "today_queue": today,

            "confidence": 0.82 if result.get("ok") else 0.4,

        }





class ContentCreatorAgent(VeridiqAgent):

    agent_type = "content_creator"



    def process(self, payload: dict[str, Any]) -> dict[str, Any]:

        from veridiq.marketing.campaigns import generate_daily_pack, get_campaign, get_or_create_default_campaign



        campaign_id = payload.get("campaign_id") or get_or_create_default_campaign()["campaign_id"]

        campaign = get_campaign(campaign_id)

        if not campaign:

            raise ValueError(f"unknown campaign_id '{campaign_id}'")

        result = generate_daily_pack(campaign_id, **_pack_kwargs(payload, created_by_agent=self.agent_type))

        return {

            "summary": result.get("message")

            or f"Generated {result.get('count', 0)} draft(s) for campaign '{campaign['name']}'.",

            "result": result,

            "confidence": 0.8 if result.get("ok") else 0.3,

        }





class SocialPosterAgent(VeridiqAgent):

    agent_type = "social_poster"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.integrations import instagram, linkedin, threads, x_twitter
        from veridiq.marketing.campaigns import generate_daily_pack, get_or_create_default_campaign

        statuses = {
            "linkedin": linkedin.status(),
            "x_twitter": x_twitter.status(),
            "instagram": instagram.status(),
            "threads": threads.status(),
        }
        campaign_id = payload.get("campaign_id") or get_or_create_default_campaign()["campaign_id"]
        requested = payload.get("channels") or ["linkedin", "instagram", "x_twitter", "threads"]
        # Honor requested specialty channels (e.g. team-run threads) even when a
        # connector is only configuration_required — drafts still queue for approval.
        known = set(statuses) | {"telegram"}
        channels = [c for c in requested if c in known] or list(statuses.keys())
        result = generate_daily_pack(
            campaign_id, **_pack_kwargs({**payload, "channels": channels}, created_by_agent=self.agent_type)
        )
        ready = [k for k, v in statuses.items() if v.get("configured")]
        return {
            "summary": result.get("message"),
            "integrations": statuses,
            "result": result,
            "confidence": 0.75 if ready else 0.4,
        }





class TelegramCommunityAgent(VeridiqAgent):

    agent_type = "telegram_community"



    def process(self, payload: dict[str, Any]) -> dict[str, Any]:

        from veridiq.integrations import telegram

        from veridiq.marketing.campaigns import generate_daily_pack, get_or_create_default_campaign



        status = telegram.status()

        campaign_id = payload.get("campaign_id") or get_or_create_default_campaign()["campaign_id"]

        result = generate_daily_pack(

            campaign_id, **_pack_kwargs({**payload, "channels": payload.get("channels") or ["telegram"]}, created_by_agent=self.agent_type)

        )

        return {

            "summary": result.get("message"),

            "integration": status,

            "result": result,

            "confidence": 0.75 if status["configured"] else 0.4,

        }





class XTwitterVoiceAgent(VeridiqAgent):

    agent_type = "x_twitter_voice"



    def process(self, payload: dict[str, Any]) -> dict[str, Any]:

        from veridiq.integrations import x_twitter



        status = x_twitter.status()

        campaign_id = payload.get("campaign_id")



        if payload.get("action") == "comment":

            from veridiq.comms import draft_marketing_content



            tweet_id = str(payload.get("target_id") or "").strip()

            text = str(payload.get("text") or "").strip()

            if not (tweet_id and text):

                raise ValueError("target_id (tweet id to reply to) and text are required to draft a reply/comment")

            draft = draft_marketing_content(
                channel="x_twitter_comment", body=text, recipient_hint=tweet_id, campaign_id=campaign_id,
                created_by_agent=self.agent_type,
            )

            return {

                "summary": "Reply/comment drafted — approve via POST /api/v1/veridiq/comms/approve (channel=x_twitter_comment) to publish.",

                "draft": draft,

                "confidence": 0.7,

            }



        from veridiq.marketing.campaigns import generate_daily_pack, get_or_create_default_campaign



        campaign_id = campaign_id or get_or_create_default_campaign()["campaign_id"]

        result = generate_daily_pack(

            campaign_id, **_pack_kwargs({**payload, "channels": payload.get("channels") or ["x_twitter"]}, created_by_agent=self.agent_type)

        )

        return {

            "summary": result.get("message"),

            "integration": status,

            "result": result,

            "confidence": 0.75 if status["configured"] else 0.4,

        }





class InfluencerRelationsAgent(VeridiqAgent):
    agent_type = "influencer_relations"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.integrations import instagram, linkedin, telegram, threads, x_twitter

        comment_readiness = {
            "x_twitter": x_twitter.status(),
            "linkedin": linkedin.status(),
            "instagram": instagram.status(),
            "telegram": telegram.status(),
            "threads": threads.status(),
        }

        if payload.get("action") == "research":
            from veridiq.influencer.research import research_creators

            research = research_creators(
                query=str(payload.get("query") or payload.get("text") or "AI verification creators").strip(),
                niche=str(payload.get("niche") or "").strip() or None,
                max_results=int(payload.get("max_results") or 8),
                summarize=payload.get("summarize", True) is not False,
            )
            return {
                "summary": research.get("message") or "Influencer research complete.",
                "research": research,
                "integrations": comment_readiness,
                "voice": "influencer",
                "confidence": 0.72 if research.get("count") else 0.4,
            }

        if payload.get("action") == "comment":
            from veridiq.comms import draft_marketing_content

            channel = str(payload.get("channel") or "").strip()
            comment_channels = {"x_twitter", "linkedin", "instagram", "telegram"}
            if channel not in comment_channels:
                raise ValueError("channel must be one of x_twitter, linkedin, instagram, telegram")
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("text is required to draft an engagement comment")
            target_ref = str(payload.get("target_ref") or "").strip()
            draft = draft_marketing_content(
                channel=f"{channel}_comment",
                body=text,
                recipient_hint=target_ref,
                campaign_id=payload.get("campaign_id"),
                created_by_agent=self.agent_type,
            )
            return {
                "summary": (
                    f"Engagement comment drafted for {channel} — approve via comms to publish "
                    "(or receive an honest configuration_required/unsupported reason)."
                ),
                "draft": draft,
                "confidence": 0.7,
            }

        from veridiq.marketing.campaigns import generate_daily_pack, get_or_create_default_campaign
        from veridiq.marketing.team_run import prepare_queue_for_run

        campaign_id = payload.get("campaign_id") or get_or_create_default_campaign()["campaign_id"]
        # Flooded queues used to make Adrian look broken (skip every run).
        if payload.get("skip_draft_generation") and payload.get("auto_clear_queue", True) is not False:
            prep = prepare_queue_for_run(campaign_id=campaign_id, auto_clear=True)
            if not prep.get("skipped"):
                payload = {**payload, "skip_draft_generation": False, "skip_reason": None, "queue_prepared": prep}
        default_channels = payload.get("channels") or ["instagram", "threads"]
        result = generate_daily_pack(
            campaign_id, **_pack_kwargs({**payload, "channels": default_channels}, created_by_agent=self.agent_type)
        )
        handoff = None
        if (
            result.get("ok")
            and result.get("drafts")
            and payload.get("handoff_to_postings", True) is not False
            and not result.get("skipped")
        ):
            try:
                from veridiq.marketing.postings_handoff import handoff_pack_drafts

                # Prefer local artifact (+ event); HTTP optional so agent runs don't hang on API lock.
                use_http = payload.get("handoff_http") is True
                handoff = handoff_pack_drafts(
                    result.get("drafts") or [],
                    created_by_agent=self.agent_type,
                    max_items=int(payload.get("handoff_max") or 2),
                    use_http=use_http,
                )
            except Exception as exc:  # noqa: BLE001 — never fail the marketing run on handoff
                handoff = {"ok": False, "status": "error", "message": str(exc)[:200]}
        ready = [k for k, v in comment_readiness.items() if v.get("configured")]
        summary = result.get("message") or f"Influencer pack queued — {result.get('count', 0)} draft(s) for approval."
        if handoff and handoff.get("count"):
            summary = f"{summary} Handed {handoff.get('count')} draft(s) toward Postings queue."
        return {
            "summary": summary,
            "integrations": comment_readiness,
            "result": result,
            "postings_handoff": handoff,
            "voice": "influencer",
            "confidence": 0.7 if ready else 0.5,
        }





MARKETING_AGENT_CLASSES: dict[str, type[VeridiqAgent]] = {

    "marketing_manager": MarketingManagerAgent,

    "content_creator": ContentCreatorAgent,

    "social_poster": SocialPosterAgent,

    "telegram_community": TelegramCommunityAgent,

    "x_twitter_voice": XTwitterVoiceAgent,

    "influencer_relations": InfluencerRelationsAgent,

}

