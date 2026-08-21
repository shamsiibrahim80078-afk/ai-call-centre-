"""AI Calling — LiveKit meetings hub + timed budget calls + legacy Twilio campaigns."""



from veridiq.calling.agent import agent_persona, handle_command

from veridiq.calling.budget import budget_status, daily_budget_seconds, max_call_seconds

from veridiq.calling.campaigns import (

    approve_campaign,

    create_campaign,

    draft_followup,

    get_campaign,

    list_campaigns,

    sync_summary_to_crm,

)

from veridiq.calling.timed_calls import (

    end_session,

    get_session,

    list_sessions,

    schedule_timed_call,

    start_session,

)

from veridiq.calling.worker import start_calling_worker, stop_calling_worker, worker_status



__all__ = [

    "agent_persona",

    "handle_command",

    "create_campaign",

    "list_campaigns",

    "get_campaign",

    "approve_campaign",

    "sync_summary_to_crm",

    "draft_followup",

    "budget_status",

    "daily_budget_seconds",

    "max_call_seconds",

    "schedule_timed_call",

    "start_session",

    "end_session",

    "get_session",

    "list_sessions",

    "start_calling_worker",

    "stop_calling_worker",

    "worker_status",

]


