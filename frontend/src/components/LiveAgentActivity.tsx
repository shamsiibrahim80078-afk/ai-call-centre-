import { useMemo } from "react";
import { Link } from "react-router-dom";
import { AgentAvatar } from "./AppShell";

type ActivityItem = {
  agent_type?: string;
  name?: string;
  role?: string;
  hue?: number;
  stage?: string;
  status_label?: string;
  task?: string;
  message?: string;
};

type Props = {
  items: ActivityItem[];
  emptyLabel?: string;
};

/** Live agent activity strip — only renders provided backend-driven items. */
export default function LiveAgentActivity({ items, emptyLabel = "Waiting for Assignment" }: Props) {
  const rows = useMemo(() => items.filter(Boolean), [items]);
  if (rows.length === 0) {
    return <p className="muted waiting-copy">{emptyLabel}</p>;
  }
  return (
    <ul className="live-activity">
      {rows.map((item, i) => (
        <li key={`${item.agent_type}-${i}`} className="live-activity-item">
          <AgentAvatar name={item.name || "A"} hue={item.hue} size={36} />
          <div>
            <strong>
              {item.name || item.agent_type}
              {item.role ? <span className="muted"> — {item.role}</span> : null}
            </strong>
            <div className="live-activity-flow">
              <span>{item.task || item.message || item.stage || "Task"}</span>
              <span className="flow-arrow" aria-hidden>
                ↓
              </span>
              <span className={`pill ${item.status_label === "Running" || item.status_label === "Working" ? "ok" : ""}`}>
                {item.status_label || item.stage || "Update"}
              </span>
            </div>
            {item.agent_type ? (
              <span style={{ display: "flex", gap: "0.75rem" }}>
                <Link className="text-link" to={`/dashboard/agents/${item.agent_type}`}>
                  Profile →
                </Link>
                <Link className="text-link" to="/dashboard/runtime">
                  Open Live Runtime →
                </Link>
              </span>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
