import { type FormEvent, useState } from "react";
import AppShell from "../components/AppShell";
import { api } from "../api/client";

const CHANNELS = [
  { value: "email", label: "Email (SMTP)" },
  { value: "linkedin", label: "LinkedIn (post)" },
  { value: "x_twitter", label: "X / Twitter (tweet)" },
  { value: "instagram", label: "Instagram (image post)" },
  { value: "threads", label: "Threads (Meta text post)" },
  { value: "telegram", label: "Telegram (message)" },
  { value: "whatsapp", label: "WhatsApp (message)" },
  { value: "marketing", label: "Marketing (webhook)" },
];

export default function CommsAssistantPage() {
  const [kind, setKind] = useState("email");
  const [context, setContext] = useState("Summarize our diligence call and propose next steps.");
  const [recipient, setRecipient] = useState("");
  const [channel, setChannel] = useState("email");
  const [draft, setDraft] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<any>(null);

  async function onDraft(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setApproval(null);
    try {
      setDraft(await api.commsDraft(kind, context, recipient));
    } catch (err: any) {
      setError(err.message || "Draft failed");
    } finally {
      setBusy(false);
    }
  }

  async function onApprove(approved: boolean) {
    if (!draft?.draft_id) return;
    setBusy(true);
    setError(null);
    try {
      setApproval(await api.commsApprove(draft.draft_id, approved, channel));
    } catch (err: any) {
      setError(err.message || "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Communication Assistant" subtitle="Drafts only — external contact requires explicit approval">
      {error ? <div className="banner error">{error}</div> : null}

      <section className="panel glass">
        <h2>Prepare a draft</h2>
        <form className="verify-form" onSubmit={onDraft}>
          <label className="muted">
            Kind
            <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="email">Outreach email</option>
              <option value="agenda">Call agenda</option>
              <option value="meeting_summary">Meeting summary</option>
              <option value="follow_up">Follow-up</option>
              <option value="contact_notes">Contact notes</option>
            </select>
          </label>
          <input
            className="field"
            placeholder="Recipient hint (email / chat id / phone / image URL — depends on send channel)"
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          />
          <textarea className="field" rows={5} value={context} onChange={(e) => setContext(e.target.value)} required />
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Drafting…" : "Create draft"}
          </button>
        </form>
      </section>

      {draft ? (
        <section className="panel glass">
          <h2>{draft.subject}</h2>
          <pre className="draft-body">{draft.body}</pre>
          <p className="muted">{draft.message}</p>
          <label className="muted" style={{ display: "block", marginTop: "0.75rem" }}>
            Send via
            <select className="field" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {CHANNELS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            Missing credentials for the selected channel return{" "}
            <code>configuration_required</code> instead of a fabricated send — nothing is
            posted/sent until the platform is configured and you approve.
          </p>
          <div className="main-actions" style={{ marginTop: "0.85rem" }}>
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void onApprove(true)}>
              Approve external action
            </button>
            <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => void onApprove(false)}>
              Reject
            </button>
          </div>
          {approval ? (
            <p className="muted" style={{ marginTop: "0.85rem" }}>
              Status: <strong>{approval.status}</strong> — {approval.message || approval.draft?.external_action_status}
            </p>
          ) : null}
        </section>
      ) : null}
    </AppShell>
  );
}
