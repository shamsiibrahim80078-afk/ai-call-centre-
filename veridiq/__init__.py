"""VERIDIQ brand constants and architecture metadata."""

APP_NAME = "VERIDIQ"
TAGLINE = "Truth. Verified. Empowered."
GREETING = "Hi, I'm VERIDIQ. Let's uncover the truth."
VERSION = "2.1.0"

HOST_BRAIN_INTRO = (
    "VERIDIQ isn't powered by a single AI. Behind the scenes, a team of specialized AI agents "
    "work together through an intelligent orchestration engine built on LangGraph. "
    "Each agent has a dedicated responsibility—from facial analysis and voice analysis to "
    "evidence retrieval, news verification, reasoning, and report generation. "
    "The orchestration layer coordinates these agents, shares context between them, "
    "manages task execution, and combines their findings into one transparent, "
    "evidence-backed truth report."
)

ARCHITECTURE_FRAMEWORK = "LangGraph"
ARCHITECTURE_VECTOR_DB = "Qdrant"
ARCHITECTURE_REALTIME = "SSE"

ARCHITECTURE = {
    "orchestrator": ARCHITECTURE_FRAMEWORK,
    "vector_db": ARCHITECTURE_VECTOR_DB,
    "realtime": ARCHITECTURE_REALTIME,
    "features": [
        "shared_memory",
        "rag",
        "retries",
        "tracing",
        "background_workers",
        "fault_recovery",
        "observability",
    ],
}

COLORS = {
    "deep_black": "#05070F",
    "midnight_blue": "#0B1224",
    "electric_blue": "#4F8CFF",
    "neon_purple": "#B14DFF",
    "white": "#F7F9FC",
    "soft_gray": "#9AA6BF",
}
