import { type FormEvent, useState } from "react";
import { api } from "../api/client";

/** Optional help assistant — collapsed by default, never blocks the dashboard. */
export default function OptionalAssistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.hostChat(question.trim());
      setAnswer(out.answer || out.message || JSON.stringify(out));
    } catch (err: any) {
      setError(err.message || "Assistant unavailable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="opt-assist">
      {open ? (
        <div className="opt-assist-panel glass" role="dialog" aria-label="Optional assistant">
          <div className="panel-head">
            <h2>Help assistant</h2>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Close
            </button>
          </div>
          <p className="muted">Optional guidance only — not part of the default landing experience.</p>
          <form className="verify-form" onSubmit={onAsk}>
            <input
              className="field"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask anything — general knowledge or VERIDIQ…"
            />
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "Thinking…" : "Ask"}
            </button>
          </form>
          {error ? <p className="banner error">{error}</p> : null}
          {answer ? <p className="assist-answer">{answer}</p> : null}
        </div>
      ) : (
        <button type="button" className="opt-assist-fab btn btn-ghost" onClick={() => setOpen(true)}>
          Help
        </button>
      )}
    </div>
  );
}
