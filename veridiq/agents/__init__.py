"""VERIDIQ specialized agents — modular, structured, confidence-scored."""

from __future__ import annotations

import io
import re
import struct
import wave
from pathlib import Path
from typing import Any, Optional

from veridiq.agents.base import VeridiqAgent
from veridiq.agents.signals import (
    duckduckgo_instant,
    emotion_profile,
    extract_claims,
    linguistic_deception_score,
    stable_unit_hash,
    tokenize,
)


class LieDetectionAgent(VeridiqAgent):
    agent_type = "lie_detection"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or payload.get("transcript") or "")
        ling = linguistic_deception_score(text)
        voice = payload.get("voice_stress") or {}
        face = payload.get("face_analysis") or {}
        voice_score = float(voice.get("stress_score") or 0)
        face_score = float(face.get("inconsistency_score") or 0)
        combined = min(1.0, ling["score"] * 0.55 + voice_score * 0.25 + face_score * 0.20)
        verdict = "high_deception_risk" if combined >= 0.65 else "moderate_risk" if combined >= 0.35 else "low_risk"
        return {
            "verdict": verdict,
            "deception_score": round(combined, 4),
            "linguistic": ling,
            "voice_component": voice_score,
            "face_component": face_score,
            "confidence": round(0.55 + min(0.4, len(tokenize(text)) / 200), 4),
        }


class FaceAnalysisAgent(VeridiqAgent):
    agent_type = "face_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        image_path = payload.get("image_path")
        image_bytes = payload.get("image_bytes")
        width = height = 0
        mode = None
        skin_ratio = 0.0
        if image_path or image_bytes:
            from PIL import Image

            if image_bytes:
                img = Image.open(io.BytesIO(image_bytes))
            else:
                img = Image.open(image_path)
            img = img.convert("RGB")
            width, height = img.size
            mode = img.mode
            # Sample pixels for skin-tone heuristic face presence
            sample = img.resize((64, 64))
            pixels = list(sample.getdata())
            skin = 0
            for r, g, b in pixels:
                if r > 95 and g > 40 and b > 20 and r > g and r > b and abs(r - g) > 15:
                    skin += 1
            skin_ratio = skin / max(1, len(pixels))
        faces_detected = 1 if skin_ratio > 0.08 else 0
        inconsistency = round(min(1.0, abs(0.22 - skin_ratio) * 2.2), 4)
        return {
            "faces_detected": faces_detected,
            "image_width": width,
            "image_height": height,
            "mode": mode,
            "skin_tone_ratio": round(skin_ratio, 4),
            "tracking_stable": faces_detected == 1,
            "inconsistency_score": inconsistency,
            "confidence": 0.72 if faces_detected else 0.4,
        }


class VoiceAnalysisAgent(VeridiqAgent):
    agent_type = "voice_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        audio_path = payload.get("audio_path")
        if not audio_path or not Path(audio_path).exists():
            # Derive proxy metrics from transcript energy if audio missing
            text = str(payload.get("text") or "")
            stress = linguistic_deception_score(text)["score"] * 0.8
            return {
                "source": "transcript_proxy",
                "stress_score": round(stress, 4),
                "rms_energy": None,
                "zero_crossing_rate": None,
                "duration_sec": None,
                "confidence": 0.45 if text else 0.2,
            }

        with wave.open(str(audio_path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            frames = wf.readframes(nframes)

        if sampwidth == 2:
            count = len(frames) // 2
            samples = struct.unpack("<" + "h" * count, frames[: count * 2])
        else:
            samples = [b - 128 for b in frames]

        if not samples:
            return {"stress_score": 0.0, "confidence": 0.2, "error": "empty_audio"}

        # Mono mix if needed
        if channels > 1:
            mono = []
            for i in range(0, len(samples), channels):
                chunk = samples[i : i + channels]
                mono.append(sum(chunk) / len(chunk))
            samples = mono

        n = len(samples)
        mean = sum(samples) / n
        rms = (sum((s - mean) ** 2 for s in samples) / n) ** 0.5
        zcr = sum(1 for i in range(1, n) if (samples[i - 1] >= 0) != (samples[i] >= 0)) / n
        duration = n / max(1, framerate)
        # Normalize stress-like score from high energy + high ZCR
        stress = min(1.0, (rms / 8000.0) * 0.6 + zcr * 4.0)
        return {
            "source": "wav_pcm",
            "channels": channels,
            "framerate": framerate,
            "duration_sec": round(duration, 3),
            "rms_energy": round(rms, 3),
            "zero_crossing_rate": round(zcr, 5),
            "stress_score": round(stress, 4),
            "confidence": 0.78,
        }


class EmotionDetectionAgent(VeridiqAgent):
    agent_type = "emotion_detection"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or payload.get("transcript") or "")
        profile = emotion_profile(text)
        return {**profile, "confidence": 0.7 if profile["intensity"] > 0 else 0.5}


class StatementVerificationAgent(VeridiqAgent):
    agent_type = "statement_verification"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        claims = extract_claims(text)
        checked = []
        for claim in claims[:8]:
            evidence = payload.get("evidence_map", {}).get(claim)
            support = 0.0
            if evidence:
                support = float(evidence.get("support_score") or 0)
            else:
                # Internal consistency heuristic
                support = 1.0 - linguistic_deception_score(claim)["score"]
            checked.append(
                {
                    "claim": claim,
                    "support_score": round(support, 4),
                    "status": "supported" if support >= 0.6 else "disputed" if support <= 0.35 else "unclear",
                }
            )
        avg = sum(c["support_score"] for c in checked) / max(1, len(checked))
        return {"claims": checked, "aggregate_support": round(avg, 4), "confidence": 0.74}


class FactCheckingAgent(VeridiqAgent):
    agent_type = "fact_checking"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        claim = str(payload.get("claim") or payload.get("text") or "")
        if not claim.strip():
            raise ValueError("claim/text required")
        search = duckduckgo_instant(claim[:180])
        abstract = (search.get("abstract") or search.get("answer") or "").lower()
        claim_tokens = set(tokenize(claim))
        overlap = len(claim_tokens & set(tokenize(abstract))) / max(1, len(claim_tokens))
        if abstract and overlap >= 0.25:
            verdict = "likely_supported"
            score = min(0.92, 0.5 + overlap)
        elif abstract:
            verdict = "partially_related"
            score = 0.45 + overlap * 0.2
        else:
            verdict = "insufficient_evidence"
            score = 0.3
        return {
            "claim": claim,
            "verdict": verdict,
            "support_score": round(score, 4),
            "source_heading": search.get("heading"),
            "abstract": search.get("abstract"),
            "abstract_url": search.get("abstract_url"),
            "related": search.get("related", [])[:5],
            "confidence": round(0.5 + min(0.4, overlap), 4),
        }


class NewsVerificationAgent(VeridiqAgent):
    agent_type = "news_verification"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("text") or payload.get("headline") or "")
        data = duckduckgo_instant(f"{query} news")
        sources = []
        for item in data.get("related") or []:
            url = item.get("url") or ""
            domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            credibility = 0.8 if any(d in domain for d in ("reuters.com", "apnews.com", "bbc.", "nytimes.com", "wikipedia.org")) else 0.55
            sources.append({"title": item.get("text"), "url": url, "domain": domain, "credibility": credibility})
        avg = sum(s["credibility"] for s in sources) / max(1, len(sources))
        return {
            "headline": query,
            "sources": sources[:6],
            "average_credibility": round(avg, 4),
            "confidence": 0.68 if sources else 0.35,
        }


class WebSearchAgent(VeridiqAgent):
    agent_type = "web_search"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("text") or "")
        if not query.strip():
            raise ValueError("query required")
        data = duckduckgo_instant(query)
        return {**data, "confidence": 0.8 if (data.get("abstract") or data.get("related")) else 0.4}


class EvidenceCollectionAgent(VeridiqAgent):
    agent_type = "evidence_collection"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = payload.get("claims") or extract_claims(str(payload.get("text") or ""))
        evidence = []
        for claim in claims[:5]:
            search = duckduckgo_instant(claim[:160])
            evidence.append(
                {
                    "claim": claim,
                    "abstract": search.get("abstract"),
                    "url": search.get("abstract_url"),
                    "related_count": len(search.get("related") or []),
                    "support_score": round(
                        min(0.95, 0.35 + 0.1 * len(search.get("related") or []) + (0.25 if search.get("abstract") else 0)),
                        4,
                    ),
                }
            )
        return {"evidence": evidence, "count": len(evidence), "confidence": 0.7 if evidence else 0.3}


class SourceCredibilityAgent(VeridiqAgent):
    agent_type = "source_credibility"

    TRUSTED = ("reuters.com", "apnews.com", "bbc.", "nytimes.com", "wikipedia.org", "nature.com", "who.int")

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        sources = payload.get("sources") or []
        scored = []
        for src in sources:
            url = str(src.get("url") or "")
            domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
            score = 0.85 if any(t in domain for t in self.TRUSTED) else 0.5
            if domain.endswith(".gov") or domain.endswith(".edu"):
                score = 0.9
            scored.append({"url": url, "domain": domain, "credibility": score})
        avg = sum(s["credibility"] for s in scored) / max(1, len(scored))
        return {"sources": scored, "average_credibility": round(avg, 4), "confidence": 0.75 if scored else 0.4}


class TimelineBuilderAgent(VeridiqAgent):
    agent_type = "timeline_builder"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        events = []
        for match in re.finditer(
            r"\b((?:19|20)\d{2}|\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})|yesterday|today|last week|on monday|on tuesday|on wednesday|on thursday|on friday)\b([^.]{10,120})",
            text,
            flags=re.I,
        ):
            events.append({"anchor": match.group(1), "detail": match.group(0).strip()})
        claims = extract_claims(text)
        for i, claim in enumerate(claims):
            events.append({"anchor": f"statement_{i+1}", "detail": claim})
        return {"events": events[:20], "confidence": 0.66 if events else 0.4}


class MeetingAnalysisAgent(VeridiqAgent):
    agent_type = "meeting_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or payload.get("transcript") or "")
        speakers = sorted(set(re.findall(r"^([A-Z][a-z]+):", text, flags=re.M)))
        decisions = [c for c in extract_claims(text) if re.search(r"\b(decide|agreed|will|action|next)\b", c, re.I)]
        return {
            "speakers_detected": speakers or ["Speaker_A"],
            "decision_items": decisions[:10],
            "word_count": len(tokenize(text)),
            "confidence": 0.7 if text else 0.3,
        }


class RiskAnalysisAgent(VeridiqAgent):
    agent_type = "risk_analysis"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        deception = float((payload.get("lie_detection") or {}).get("deception_score") or 0)
        credibility = float((payload.get("credibility") or {}).get("average_credibility") or 0.5)
        emotion = payload.get("emotion") or {}
        intensity = float(emotion.get("intensity") or 0)
        risk = min(1.0, deception * 0.5 + (1 - credibility) * 0.35 + intensity * 0.15)
        level = "critical" if risk >= 0.75 else "high" if risk >= 0.55 else "medium" if risk >= 0.35 else "low"
        return {"risk_score": round(risk, 4), "risk_level": level, "confidence": 0.76}


class ConfidenceScoringAgent(VeridiqAgent):
    agent_type = "confidence_scoring"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        scores = [float(v) for v in (payload.get("scores") or []) if v is not None]
        if not scores:
            for key in ("lie_detection", "fact_checking", "news_verification", "source_credibility"):
                block = payload.get(key) or {}
                if "confidence" in block:
                    scores.append(float(block["confidence"]))
        if not scores:
            return {"overall_confidence": 0.0, "confidence": 0.2}
        overall = sum(scores) / len(scores)
        return {
            "overall_confidence": round(overall, 4),
            "components": scores,
            "confidence": round(min(0.95, 0.5 + len(scores) * 0.08), 4),
        }


class ReportGeneratorAgent(VeridiqAgent):
    agent_type = "report_generator"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "title": payload.get("title") or "VERIDIQ Truth Report",
            "truth_score": payload.get("truth_score"),
            "risk_level": (payload.get("risk_analysis") or {}).get("risk_level"),
            "key_findings": payload.get("key_findings") or [],
            "citations": payload.get("citations") or [],
        }
        narrative = (
            f"VERIDIQ assessed the submitted material with an overall truth confidence of "
            f"{summary.get('truth_score')}. Risk level: {summary.get('risk_level')}."
        )
        return {"summary": summary, "narrative": narrative, "confidence": 0.8}


class CitationAgent(VeridiqAgent):
    agent_type = "citation"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload.get("evidence") or []
        citations = []
        for i, item in enumerate(evidence, start=1):
            citations.append(
                {
                    "id": f"C{i}",
                    "claim": item.get("claim"),
                    "url": item.get("url"),
                    "note": (item.get("abstract") or "")[:180],
                }
            )
        return {"citations": citations, "confidence": 0.85 if citations else 0.4}


class ConversationMemoryAgent(VeridiqAgent):
    agent_type = "conversation_memory"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from memory.memory_manager import MemoryManager

        session_id = str(payload.get("session_id") or "default")
        mm = MemoryManager(default_agent_uuid=f"veridiq-memory-{session_id}")
        turn = payload.get("turn")
        if turn:
            history = mm.load_memory("conversation", default=[])
            if not isinstance(history, list):
                history = []
            history.append(turn)
            mm.save_memory("conversation", history[-50:], tags=["veridiq", "conversation"])
        history = mm.load_memory("conversation", default=[])
        return {"session_id": session_id, "turns": history, "confidence": 0.9}


class DecisionAgent(VeridiqAgent):
    agent_type = "decision"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        truth = float(payload.get("truth_score") or 0)
        risk = float((payload.get("risk_analysis") or {}).get("risk_score") or 0)
        if truth >= 0.7 and risk < 0.45:
            decision = "accept_as_likely_true"
        elif truth <= 0.35 or risk >= 0.7:
            decision = "flag_for_human_review"
        else:
            decision = "needs_more_evidence"
        return {"decision": decision, "truth_score": truth, "risk_score": risk, "confidence": 0.77}


class OrchestratorAgent(VeridiqAgent):
    agent_type = "orchestrator"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Routing recommendation based on available inputs
        route = ["statement_verification", "fact_checking", "confidence_scoring", "decision"]
        if payload.get("audio_path"):
            route.insert(0, "voice_analysis")
        if payload.get("image_path") or payload.get("image_bytes"):
            route.insert(0, "face_analysis")
        if payload.get("text") or payload.get("transcript"):
            route = ["emotion_detection", "lie_detection"] + route
        return {"recommended_route": route, "confidence": 0.88}


AGENT_REGISTRY: dict[str, type[VeridiqAgent]] = {
    "lie_detection": LieDetectionAgent,
    "face_analysis": FaceAnalysisAgent,
    "voice_analysis": VoiceAnalysisAgent,
    "emotion_detection": EmotionDetectionAgent,
    "statement_verification": StatementVerificationAgent,
    "fact_checking": FactCheckingAgent,
    "news_verification": NewsVerificationAgent,
    "web_search": WebSearchAgent,
    "evidence_collection": EvidenceCollectionAgent,
    "source_credibility": SourceCredibilityAgent,
    "timeline_builder": TimelineBuilderAgent,
    "meeting_analysis": MeetingAnalysisAgent,
    "risk_analysis": RiskAnalysisAgent,
    "confidence_scoring": ConfidenceScoringAgent,
    "report_generator": ReportGeneratorAgent,
    "citation": CitationAgent,
    "conversation_memory": ConversationMemoryAgent,
    "decision": DecisionAgent,
    "orchestrator": OrchestratorAgent,
}

# Market intelligence specialists
from veridiq.agents.market import MARKET_AGENT_CLASSES  # noqa: E402

AGENT_REGISTRY.update(MARKET_AGENT_CLASSES)

# Growth specialists — AI Calling, LinkedIn outreach, Sales intelligence
from veridiq.agents.growth import GROWTH_AGENT_CLASSES  # noqa: E402

AGENT_REGISTRY.update(GROWTH_AGENT_CLASSES)

# Marketing Agency — Marketing Manager, Content Creator, Social Poster,
# Telegram Community, X/Twitter Voice, Influencer Relations
from veridiq.agents.marketing import MARKETING_AGENT_CLASSES  # noqa: E402

AGENT_REGISTRY.update(MARKETING_AGENT_CLASSES)

# Executive leadership — CEO + Directors (Agent SDK coordination)
from veridiq.agents.leadership import LEADERSHIP_AGENT_CLASSES  # noqa: E402

AGENT_REGISTRY.update(LEADERSHIP_AGENT_CLASSES)


def get_agent(agent_type: str) -> VeridiqAgent:
    cls = AGENT_REGISTRY.get(agent_type)
    if cls is None:
        raise KeyError(f"Unknown agent_type '{agent_type}'")
    return cls()
