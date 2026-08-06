"""AI Host conversational replies for the Home Dashboard assistant.

Primary path: ai_gateway LLM with a general-knowledge system prompt.
Research tasks ("deep research", "find out", "nikaal do") run multi_search + extract.
Offline fallback: product FAQ for clear VERIDIQ questions only — never force every
answer into a VERIDIQ pitch.
"""

from __future__ import annotations

import re
from typing import Any

# Exported for unit tests — must not forbid general knowledge.
HOST_SYSTEM_PROMPT = """You are a capable general AI assistant embedded in VERIDIQ.

Core behavior (priority order):
1. Answer ANY topic fully and clearly — science, technology, blockchain, history, math,
   culture, how-tos, comparisons, coding help, current-events reasoning from your knowledge.
   Be thorough and useful. VERIDIQ is the product shell you live in; it is NOT the default
   subject of conversation.
2. Do NOT pivot unrelated questions into VERIDIQ marketing. If the user asks "what is a
   blockchain" or "explain photosynthesis", answer that topic normally. Only mention VERIDIQ
   when they ask about the product or a platform action, or when it genuinely helps.
3. When they ask about VERIDIQ / verification / agents / uploads / LangGraph / RAG / reports /
   workforce / marketing / calling / integrations, explain accurately and suggest concrete
   next steps in the app when useful.
4. When they ask you to research / deep-research / find out / look up / "nikaal do" something,
   rely on live search results provided in context (if any). Do not invent sources or URLs.

Product context (use only when relevant):
VERIDIQ is an enterprise truth-verification platform. Specialized AI agents collaborate through
LangGraph to analyze claims, media, and evidence, with RAG (Qdrant), confidence scoring, PDF
reports, and optional blockchain attestation of report hashes.

Safety:
- No assistance with criminal activity.
- Do not invent live API secrets, credentials, or claim blockchain posts/attestations succeeded
  unless the user provides real confirmation from the app.
- Be honest when you lack live system state or search results.
- Do not compare yourself to other AI products or brand yourself as one.
- Never say you can "talk like ChatGPT", "are like ChatGPT", or similar self-branding.
  Just be a capable, helpful assistant without naming or mirroring other products.

Reply in clear prose (no JSON). Prefer structured explanations with short examples when helpful.
"""

# Product FAQ — used only when LLM is unavailable, and only for clear product intent.
_PRODUCT_TOPICS: list[tuple[list[str], str]] = [
    (
        ["what is veridiq", "about veridiq", "veridiq is"],
        "VERIDIQ is an enterprise truth-verification platform. Specialized AI agents collaborate through LangGraph to analyze claims, media, and evidence, then produce confidence-scored reports.",
    ),
    (
        ["mission", "why veridiq", "why was veridiq"],
        "VERIDIQ exists to make truth verification fast, explainable, and operational—Truth. Verified. Empowered.",
    ),
    (
        ["upload", "video", "mp4", "webm", "mov"],
        "Go to Verify and use media upload for MP4/WebM/MOV. The pipeline extracts audio and can seed facial analysis before LangGraph orchestration.",
    ),
    (
        ["audio", "voice", "wav", "mp3", "m4a"],
        "Upload WAV/MP3/M4A for voice-stress analysis. Those signals blend with linguistic deception markers in the lie-detection agent.",
    ),
    (
        ["meeting transcript", "meeting analysis"],
        "Paste a meeting transcript into Verify. Meeting analysis and timeline agents extract topics, speakers, and chronology.",
    ),
    (
        ["news verification", "verify news"],
        "News verification and web-search agents gather corroborating sources; credibility scoring weights the final truth estimate.",
    ),
    (
        ["facial", "face analysis"],
        "When an image or video frame is available, the face analysis agent estimates presence and inconsistency cues for deception scoring.",
    ),
    (
        ["rag", "qdrant", "vector"],
        "Qdrant stores semantic evidence embeddings. Before fact-checking, RAG retrieves related neighbors into shared memory for stronger verification.",
    ),
    (
        ["langgraph", "orchestr"],
        "LangGraph routes route → perception → evidence/RAG → verification → reasoning → report, with parallel agents, retries, and traced shared memory.",
    ),
    (
        ["confidence", "truth score", "pdf report"],
        "Confidence scoring blends deception, factual support, credibility, and RAG strength into a truth score, then generates a professional PDF report.",
    ),
    (
        ["attest", "blockchain attestation", "truthattestation"],
        "A modular blockchain layer can attest report hashes once contract addresses and wallet env vars are configured—supporting Hardhat, Sepolia, Base, and Ethereum.",
    ),
    (
        ["privacy", "security", "jwt", "bcrypt"],
        "JWT sessions, bcrypt passwords, upload validation, rate limits, and env-managed secrets protect the platform. Raw credentials are never logged.",
    ),
    (
        ["specialized agents", "how many agents", "agent roster"],
        "Nineteen specialized agents are live—face, voice, emotion, lie detection, evidence, news, fact-checking, risk, confidence, report generation, and more—all wired through LangGraph.",
    ),
]

_PRODUCT_INTENT = re.compile(
    r"\b(veridiq|verify|verification|langgraph|qdrant|rag|workforce|attestation|"
    r"upload|dashboard|truth.?score|lie.?detect|deception)\b",
    re.I,
)

# Phrases that must never appear as "refuse general knowledge" guardrails.
_FORBIDDEN_PROMPT_PHRASES = (
    "only answer about veridiq",
    "refuse off-topic",
    "off-topic",
    "everything must relate",
    "only discuss veridiq",
    "do not answer general",
    "stay on topic about veridiq",
)


def prompt_allows_general_knowledge() -> bool:
    """Unit-test helper: host system prompt must invite general Q&A, not forbid it."""
    text = HOST_SYSTEM_PROMPT.lower()
    if any(p in text for p in _FORBIDDEN_PROMPT_PHRASES):
        return False
    return "general" in text and "any topic" in text


def _looks_like_general_definition(question: str) -> bool:
    q = (question or "").strip().lower()
    if _PRODUCT_INTENT.search(q):
        return False
    return bool(
        re.match(
            r"^(what(?:'s| is| are| was| were)|who(?:'s| is| are)|define|explain|tell me about|"
            r"how does|how do|how can|why (?:is|are|do|does)|compare)\b",
            q,
        )
    )


def _faq_answer(question: str) -> dict[str, Any] | None:
    """Offline product FAQ — skip for clear general-knowledge questions."""
    q = (question or "").strip().lower()
    if not q:
        return None
    if _looks_like_general_definition(q):
        return None
    for keys, answer in _PRODUCT_TOPICS:
        if any(k in q for k in keys):
            return {"answer": answer, "topic": keys[0], "ok": True, "source": "faq"}
    tokens = set(re.findall(r"[a-z0-9]+", q))
    if tokens & {"help", "start", "how"} and _PRODUCT_INTENT.search(q):
        return {
            "answer": "Start on the Verify tab: paste a statement or upload media. Watch LangGraph agents light up live via SSE, then download the PDF report.",
            "topic": "help",
            "ok": True,
            "source": "faq",
        }
    return None


def _run_deep_research(question: str) -> dict[str, Any] | None:
    """If the user asked for research / extract / nikaal-do, run live multi_search."""
    from veridiq.research.deep_research import (
        deep_research,
        extract_research_query,
        format_research_answer,
        looks_like_research_task,
    )

    if not looks_like_research_task(question):
        return None
    query = extract_research_query(question)
    research = deep_research(query=query or question, max_results=8, summarize=True)
    answer = format_research_answer(research)
    return {
        "answer": answer[:8000],
        "topic": "deep_research",
        "ok": bool(research.get("ok") or research.get("status") == "configuration_required"),
        "source": "deep_research",
        "research": {
            "status": research.get("status"),
            "query": research.get("query"),
            "count": research.get("count"),
            "providers_used": research.get("providers_used"),
            "results": (research.get("results") or [])[:8],
            "message": research.get("message"),
        },
    }


def _llm_answer(question: str, *, research_context: str = "") -> dict[str, Any] | None:
    try:
        from veridiq.integrations import ai_gateway

        st = ai_gateway.status()
        if not st.get("configured"):
            return None
        extra = ""
        if research_context:
            extra = (
                "\n\nLive research context (cite only these sources; do not invent URLs):\n"
                f"{research_context[:3500]}\n"
            )
        prompt = (
            f"{HOST_SYSTEM_PROMPT}{extra}\n\nUser question:\n{(question or '').strip()[:2500]}\n\nAssistant:"
        )
        gen = ai_gateway.generate(
            prompt=prompt,
            task_type="reason",
            max_providers=4,
            max_tokens=1200,
        )
        if not gen.get("ok"):
            return None
        text = str(gen.get("text") or "").strip()
        if not text:
            return None
        return {
            "answer": text[:8000],
            "topic": "llm",
            "ok": True,
            "source": "llm",
            "provider_used": gen.get("provider_used"),
        }
    except Exception:
        return None


def answer_host_question(question: str) -> dict[str, Any]:
    q_raw = (question or "").strip()
    if not q_raw:
        return {
            "answer": (
                "Ask me anything — general knowledge on any topic, "
                "deep research tasks, or VERIDIQ product help when you need it."
            ),
            "topic": "empty",
            "ok": True,
            "source": "empty",
        }

    q = q_raw.lower()
    tokens = set(re.findall(r"[a-z0-9]+", q))
    if tokens & {"hi", "hello", "hey", "hola", "namaste"} or q in {"hi", "hello", "hey"}:
        return {
            "answer": (
                "Hi! I'm your VeriDiQ assistant — I answer any topic in depth "
                "(science, tech, history, how-tos). I can also run deep research "
                "when you ask, or help with VERIDIQ product features. What would you like to know?"
            ),
            "topic": "greeting",
            "ok": True,
            "source": "greeting",
        }

    # Research / deep-research / "nikaal do" → live search first.
    research_out = _run_deep_research(q_raw)
    if research_out:
        # Prefer research answer; optional LLM polish only when search returned hits.
        research_meta = research_out.get("research") or {}
        if research_meta.get("status") == "configuration_required":
            return research_out
        if research_meta.get("count"):
            ctx_lines = []
            for r in research_meta.get("results") or []:
                ctx_lines.append(
                    f"- {r.get('title')}: {r.get('url')} — {(r.get('snippet') or '')[:160]}"
                )
            polished = _llm_answer(q_raw, research_context="\n".join(ctx_lines))
            if polished and polished.get("answer"):
                polished["topic"] = "deep_research"
                polished["source"] = "deep_research_llm"
                polished["research"] = research_meta
                return polished
        return research_out

    # Prefer LLM for rich general + product answers.
    llm = _llm_answer(q_raw)
    if llm:
        return llm

    faq = _faq_answer(q_raw)
    if faq:
        return faq

    if _looks_like_general_definition(q_raw):
        return {
            "answer": (
                "I'd give a full general-knowledge answer here (definitions, examples, comparisons), "
                "but no LLM provider is configured right now. Set a provider key "
                "(e.g. VERIDIQ_GROQ_API_KEY or VERIDIQ_OPENROUTER_API_KEY) and ask again. "
                "I can still answer offline about VERIDIQ features — uploads, LangGraph, RAG, reports."
            ),
            "topic": "general_needs_llm",
            "ok": True,
            "source": "offline",
        }

    return {
        "answer": (
            "I can help with general knowledge on any topic when an LLM key is configured, "
            "run deep research when search keys are set, and answer VERIDIQ product topics offline "
            "(uploads, agents, LangGraph, RAG, confidence reports, privacy, blockchain attestation). "
            "What would you like to explore?"
        ),
        "topic": "general",
        "ok": True,
        "source": "offline",
    }
