import { useEffect, useMemo, useState } from "react";

const NODES = [
  "User Input",
  "Frontend",
  "Backend API",
  "AI Orchestrator (LangGraph)",
  "Shared Memory + Context",
  "Specialized AI Agents",
  "Vector Database (RAG / Qdrant)",
  "Evidence Retrieval",
  "Reasoning Engine",
  "Confidence Scoring",
  "Truth Report",
  "Interactive Dashboard",
] as const;

const AGENT_BRANCH = ["Face", "Voice", "Evidence", "News"] as const;

type ArchitectureFlowProps = {
  active?: boolean;
  onComplete?: () => void;
};

export default function ArchitectureFlow({ active = true, onComplete }: ArchitectureFlowProps) {
  const [step, setStep] = useState(0);
  const [showBranch, setShowBranch] = useState(false);
  const reduceMotion = useMemo(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    []
  );

  useEffect(() => {
    if (!active) return;
    if (reduceMotion) {
      setStep(NODES.length - 1);
      setShowBranch(true);
      const t = window.setTimeout(() => onComplete?.(), 900);
      return () => window.clearTimeout(t);
    }

    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setStep(i);
      if (i === 5) setShowBranch(true);
      if (i >= NODES.length - 1) {
        window.clearInterval(id);
        window.setTimeout(() => onComplete?.(), 1100);
      }
    }, 420);
    return () => window.clearInterval(id);
  }, [active, onComplete, reduceMotion]);

  const label = NODES.map((n, idx) => `${idx + 1}. ${n}`).join(". ");

  return (
    <div
      className="arch-flow"
      role="img"
      aria-label={`VERIDIQ enterprise AI pipeline: ${label}`}
    >
      <p className="arch-title">Enterprise AI Brain</p>
      <p className="arch-sub">LangGraph orchestration · Qdrant RAG · shared memory · live SSE</p>
      <div className="arch-stack">
        {NODES.map((name, idx) => {
          const lit = step >= idx;
          const current = step === idx;
          return (
            <div key={name} className="arch-row">
              {idx > 0 ? (
                <div className={`arch-edge ${lit ? "is-on" : ""}`} aria-hidden>
                  <span className={`arch-packet ${current && !reduceMotion ? "is-moving" : ""}`} />
                </div>
              ) : null}
              <div className={`arch-node ${lit ? "is-lit" : ""} ${current ? "is-current" : ""}`}>
                {name}
              </div>
              {name === "Specialized AI Agents" && showBranch ? (
                <div className="arch-branch" aria-hidden>
                  {AGENT_BRANCH.map((a) => (
                    <span key={a} className="arch-chip">
                      {a}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <style>{`
        .arch-flow {
          width: min(520px, 92vw);
          margin: 0 auto;
          text-align: center;
          animation: fadeUp 500ms ease both;
        }
        .arch-title {
          margin: 0 0 0.35rem;
          font-size: 1.05rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          background: linear-gradient(120deg, #F7F9FC, #4F8CFF 50%, #B14DFF);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          font-weight: 700;
        }
        .arch-sub {
          margin: 0 0 1.1rem;
          color: #9AA6BF;
          font-size: 0.78rem;
        }
        .arch-stack {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
          max-height: min(58vh, 520px);
          overflow: auto;
          padding: 0.25rem 0.5rem 0.75rem;
        }
        .arch-row { width: 100%; display: flex; flex-direction: column; align-items: center; }
        .arch-edge {
          width: 2px;
          height: 18px;
          background: rgba(154,166,191,0.2);
          position: relative;
          transition: background 300ms ease;
        }
        .arch-edge.is-on {
          background: linear-gradient(180deg, #4F8CFF, #B14DFF);
          box-shadow: 0 0 12px rgba(79,140,255,0.45);
        }
        .arch-packet {
          position: absolute;
          left: 50%;
          top: 0;
          width: 7px;
          height: 7px;
          margin-left: -3.5px;
          border-radius: 50%;
          background: #F7F9FC;
          opacity: 0;
        }
        .arch-packet.is-moving {
          opacity: 1;
          animation: packetDrop 420ms linear;
        }
        @keyframes packetDrop {
          from { transform: translateY(0); opacity: 1; }
          to { transform: translateY(14px); opacity: 0.2; }
        }
        .arch-node {
          width: 100%;
          max-width: 360px;
          padding: 0.55rem 0.85rem;
          border-radius: 12px;
          border: 1px solid rgba(154,166,191,0.18);
          background: rgba(11,18,36,0.55);
          color: #9AA6BF;
          font-size: 0.82rem;
          font-weight: 500;
          transition: border-color 280ms ease, color 280ms ease, box-shadow 280ms ease, background 280ms ease;
        }
        .arch-node.is-lit {
          color: #F7F9FC;
          border-color: rgba(79,140,255,0.45);
          background: rgba(79,140,255,0.12);
        }
        .arch-node.is-current {
          box-shadow: 0 0 0 1px rgba(177,77,255,0.45), 0 8px 28px rgba(79,140,255,0.22);
          border-color: rgba(177,77,255,0.55);
        }
        .arch-branch {
          display: flex;
          flex-wrap: wrap;
          gap: 0.35rem;
          justify-content: center;
          margin: 0.45rem 0 0.15rem;
          animation: fadeUp 400ms ease both;
        }
        .arch-chip {
          padding: 0.2rem 0.55rem;
          border-radius: 999px;
          font-size: 0.7rem;
          color: #F7F9FC;
          background: linear-gradient(135deg, rgba(79,140,255,0.35), rgba(177,77,255,0.28));
          border: 1px solid rgba(79,140,255,0.25);
        }
        @media (prefers-reduced-motion: reduce) {
          .arch-packet.is-moving { animation: none; opacity: 0; }
        }
      `}</style>
    </div>
  );
}
