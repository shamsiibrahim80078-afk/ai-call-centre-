import { type FormEvent, useEffect, useMemo, useState } from "react";
import HostAvatar from "./HostAvatar";
import { api } from "../api/client";

const KEYNOTE_BEATS = [
  {
    title: "What VERIDIQ is",
    body: "VERIDIQ is an enterprise truth-verification platform. Specialized AI agents collaborate to analyze statements, media, and sources—then deliver transparent, evidence-backed reports.",
  },
  {
    title: "Why it was created",
    body: "Misinformation moves faster than manual review. VERIDIQ was built so organizations can verify claims with speed, auditability, and multi-signal confidence—not gut feel.",
  },
  {
    title: "Mission",
    body: "Truth. Verified. Empowered. Our mission is to make verification measurable, explainable, and operational at enterprise scale.",
  },
  {
    title: "Core features",
    body: "Live multi-agent analysis, LangGraph orchestration, Qdrant RAG, SSE progress streams, confidence scoring, PDF truth reports, and a blockchain-ready attestation layer.",
  },
  {
    title: "Upload video",
    body: "Use Verify → upload to submit MP4/WebM/MOV. The pipeline extracts audio, derives speech signals, and can seed facial analysis from frame proxies.",
  },
  {
    title: "Upload audio",
    body: "Upload WAV/MP3/M4A for voice-stress analysis. Stress metrics feed the lie-detection agent alongside linguistic markers.",
  },
  {
    title: "Analyze meetings",
    body: "Paste a transcript or meeting notes. The meeting analysis and timeline agents extract speakers, topics, and chronologies automatically.",
  },
  {
    title: "Verify news",
    body: "The news verification and web-search agents gather corroborating sources; source credibility scores weight the final truth estimate.",
  },
  {
    title: "Facial analysis",
    body: "When imagery is present, the face analysis agent estimates presence, tracking stability, and inconsistency signals used in deception scoring.",
  },
  {
    title: "Voice analysis",
    body: "Voice agents compute energy and stress proxies from audio waveforms and blend them with linguistic deception cues.",
  },
  {
    title: "Evidence & RAG",
    body: "Evidence collection plus Qdrant semantic retrieval pull related facts into shared memory before fact-checking and citation.",
  },
  {
    title: "LangGraph orchestration",
    body: "LangGraph routes perception, evidence, verification, and reasoning stages—sharing context, running agents in parallel, retrying failures, and tracing every step.",
  },
  {
    title: "Confidence & reports",
    body: "Confidence scoring blends deception, support, credibility, and RAG strength into a truth score, then the report generator produces a professional PDF.",
  },
  {
    title: "Blockchain readiness",
    body: "A modular blockchain service can attest report hashes once contract addresses are configured—supporting EVM networks without hardcoding deployments.",
  },
  {
    title: "Privacy",
    body: "Sessions use JWT auth, uploads are validated and sandboxed, secrets live in environment variables, and logs avoid storing raw credentials.",
  },
];

type Msg = { role: "host" | "user"; text: string };

export default function AIHostPanel({ visible }: { visible: boolean }) {
  const [entered, setEntered] = useState(false);
  const [beat, setBeat] = useState(0);
  const [typed, setTyped] = useState("");
  const [introDone, setIntroDone] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!visible) return;
    const t = window.setTimeout(() => setEntered(true), 80);
    return () => window.clearTimeout(t);
  }, [visible]);

  const current = KEYNOTE_BEATS[Math.min(beat, KEYNOTE_BEATS.length - 1)];

  useEffect(() => {
    if (!entered || introDone) return;
    setSpeaking(true);
    setTyped("");
    let i = 0;
    const text = `${current.title}. ${current.body}`;
    const id = window.setInterval(() => {
      i += 1;
      setTyped(text.slice(0, i));
      if (i >= text.length) {
        window.clearInterval(id);
        setSpeaking(false);
        window.setTimeout(() => {
          if (beat < KEYNOTE_BEATS.length - 1) setBeat((b) => b + 1);
          else {
            setIntroDone(true);
            setMessages([
              {
                role: "host",
                text: "I'm ready when you are. Ask me anything — general knowledge (science, tech, blockchain) or VERIDIQ (uploads, agents, LangGraph, RAG, reports).",
              },
            ]);
          }
        }, 900);
      }
    }, 12);
    return () => window.clearInterval(id);
  }, [entered, beat, introDone, current.title, current.body]);

  const progress = useMemo(
    () => Math.round(((introDone ? KEYNOTE_BEATS.length : beat + 1) / KEYNOTE_BEATS.length) * 100),
    [beat, introDone]
  );

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    setAsking(true);
    setSpeaking(true);
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    try {
      const res = await api.hostChat(q);
      setMessages((m) => [...m, { role: "host", text: res.answer || "I can help with that in the Verify console." }]);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "host",
          text: "I hit a connectivity issue. You can still run verifications from the Verify tab while I reconnect.",
        },
      ]);
    } finally {
      setAsking(false);
      setSpeaking(false);
    }
  }

  if (!visible) return null;

  return (
    <section className={`host-panel glass ${entered ? "is-in" : ""}`}>
      <div className="host-left">
        <HostAvatar speaking={speaking} phase={introDone ? "Assistant" : "Keynote"} />
        <div className="host-progress">
          <span>Introduction</span>
          <strong>{progress}%</strong>
        </div>
      </div>
      <div className="host-right">
        <h2>AI Host</h2>
        {!introDone ? (
          <>
            <p className="host-beat-title">{current.title}</p>
            <p className="host-script">{typed}</p>
            <button type="button" className="btn btn-ghost" onClick={() => setIntroDone(true)}>
              Skip keynote
            </button>
          </>
        ) : (
          <>
            <div className="host-chat" aria-live="polite">
              {messages.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  {m.text}
                </div>
              ))}
            </div>
            <form className="host-ask" onSubmit={onAsk}>
              <input
                className="field"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask anything — general knowledge or VERIDIQ…"
                aria-label="Ask the AI Host"
              />
              <button className="btn btn-primary" type="submit" disabled={asking || !question.trim()}>
                {asking ? "Thinking…" : "Ask"}
              </button>
            </form>
          </>
        )}
      </div>
      <style>{`
        .host-panel {
          display: grid; grid-template-columns: 180px 1fr; gap: 1.25rem;
          padding: 1.2rem 1.35rem; margin-bottom: 1rem; border-radius: 20px;
          opacity: 0; transform: translateY(18px);
          transition: opacity 700ms ease, transform 700ms ease;
        }
        .host-panel.is-in { opacity: 1; transform: none; }
        .host-left { display: grid; justify-items: center; align-content: start; gap: 0.75rem; }
        .host-progress {
          display: flex; justify-content: space-between; width: 100%;
          font-size: 0.72rem; color: #9AA6BF;
        }
        .host-right h2 { margin: 0 0 0.55rem; font-size: 1.05rem; }
        .host-beat-title { margin: 0 0 0.45rem; color: #4F8CFF; font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; }
        .host-script { margin: 0 0 1rem; color: #c8d0e4; line-height: 1.65; min-height: 5.5rem; }
        .host-chat {
          max-height: 220px; overflow: auto; display: grid; gap: 0.55rem; margin-bottom: 0.75rem;
        }
        .bubble {
          padding: 0.7rem 0.85rem; border-radius: 12px; font-size: 0.9rem; line-height: 1.5;
        }
        .bubble.host { background: rgba(79,140,255,0.12); border: 1px solid rgba(79,140,255,0.2); }
        .bubble.user { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); justify-self: end; }
        .host-ask { display: flex; gap: 0.55rem; }
        .host-ask .field { flex: 1; }
        @media (max-width: 800px) {
          .host-panel { grid-template-columns: 1fr; }
        }
      `}</style>
    </section>
  );
}
