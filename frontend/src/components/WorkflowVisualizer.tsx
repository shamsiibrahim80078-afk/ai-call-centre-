import { useMemo } from "react";

const STAGES = [
  "user_request",
  "task_planner",
  "agent_assignment",
  "evidence_retrieval",
  "verification",
  "reasoning",
  "report_generation",
  "completed",
] as const;

const STAGE_ALIASES: Record<string, string> = {
  route: "task_planner",
  market_plan: "task_planner",
  delegation: "agent_assignment",
  agent_start: "agent_assignment",
  agent_complete: "agent_assignment",
  perception: "evidence_retrieval",
  evidence_rag: "evidence_retrieval",
  rag: "evidence_retrieval",
  rag_hits: "evidence_retrieval",
  market_evidence: "evidence_retrieval",
  verification: "verification",
  reasoning: "reasoning",
  market_reasoning: "reasoning",
  confidence: "reasoning",
  report_ready: "report_generation",
  completed: "completed",
  failed: "completed",
};

type Props = {
  events: { stage?: string }[];
  active?: boolean;
};

export default function WorkflowVisualizer({ events, active }: Props) {
  const current = useMemo(() => {
    let idx = active ? 0 : -1;
    for (const ev of events) {
      const mapped = STAGE_ALIASES[ev.stage || ""] || ev.stage;
      const i = STAGES.indexOf(mapped as (typeof STAGES)[number]);
      if (i > idx) idx = i;
    }
    return idx;
  }, [events, active]);

  return (
    <div className="wf-viz" aria-label="Live workflow visualization">
      {STAGES.map((stage, i) => (
        <div key={stage} className={`wf-viz-node ${i <= current ? "is-on" : ""} ${i === current && active ? "is-pulse" : ""}`}>
          <span>{stage.replace(/_/g, " ")}</span>
          {i < STAGES.length - 1 ? <span className="wf-viz-arrow" aria-hidden>
            ↓
          </span> : null}
        </div>
      ))}
    </div>
  );
}
