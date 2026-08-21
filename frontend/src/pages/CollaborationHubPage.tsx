import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AppShell, { AgentAvatar } from "../components/AppShell";
import { api } from "../api/client";

type AgentCard = {
  agent_type?: string;
  name: string;
  role?: string;
  avatar_hue?: number;
  avatar_presentation?: string;
  avatar_hair?: string;
  avatar_skin?: string;
  avatar_hair_color?: string;
};

type DmContact = AgentCard & {
  dm_thread_id?: string | null;
  preview?: string;
  preview_sender?: string;
  updated_at?: string;
  message_count?: number;
  unread?: number;
  status?: string;
};

type ThreadMsg = {
  message_id: string;
  agent_id?: string;
  sender_name?: string;
  body: string;
  kind?: string;
  created_at: string;
  avatar?: AgentCard;
};

type HubInvite = {
  invite_id: string;
  thread_id?: string;
  meeting_id?: string | null;
  status: string;
  message?: string;
  invited_by?: AgentCard;
  invited_by_agent?: string;
};

type AgentMeetProposal = {
  proposal_id: string;
  status: string;
  topic?: string;
  thread_id?: string;
  meeting_id?: string | null;
  countdown_remaining_seconds?: number | null;
  proposer?: AgentCard;
  invitee?: AgentCard;
};

type LiveThread = {
  thread_id: string;
  title: string;
  topic: string;
  status: string;
  participants?: AgentCard[];
  preview?: string;
  preview_sender?: string;
  message_count?: number;
  updated_at?: string;
};

function formatTime(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    if (sameDay) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

function AvatarProps(a: Partial<AgentCard>) {
  return {
    name: a.name || "A",
    hue: a.avatar_hue ?? 210,
    presentation: a.avatar_presentation,
    hair: a.avatar_hair,
    skin: a.avatar_skin,
    hairColor: a.avatar_hair_color,
    roleHint: a.role,
  };
}

function isUserMessage(m: ThreadMsg, userName: string): boolean {
  if (m.agent_id) return false;
  if (m.kind === "system" || m.kind === "invite") return false;
  const who = (m.sender_name || "").trim().toLowerCase();
  return who === "you" || who === userName.toLowerCase() || who === "ibrahim";
}

export default function CollaborationHubPage() {
  const [tab, setTab] = useState<"dms" | "rooms">("dms");
  const [contacts, setContacts] = useState<DmContact[]>([]);
  const [rooms, setRooms] = useState<LiveThread[]>([]);
  const [invites, setInvites] = useState<HubInvite[]>([]);
  const [proposals, setProposals] = useState<AgentMeetProposal[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ThreadMsg[]>([]);
  const [activeAgent, setActiveAgent] = useState<DmContact | null>(null);
  const [search, setSearch] = useState("");
  const [notifOpen, setNotifOpen] = useState(false);
  const [mobileShowChat, setMobileShowChat] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingChat, setLoadingChat] = useState(false);
  const [userName, setUserName] = useState("Ibrahim");
  const [compose, setCompose] = useState("");
  const [composeHint, setComposeHint] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const notifRef = useRef<HTMLDivElement | null>(null);

  const pending = useMemo(() => invites.filter((i) => i.status === "pending"), [invites]);
  const openProposals = useMemo(
    () => proposals.filter((p) => ["proposed", "approved", "live"].includes(p.status)),
    [proposals],
  );
  const notifCount = pending.length + openProposals.length;

  const filteredContacts = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return contacts;
    return contacts.filter(
      (c) =>
        (c.name || "").toLowerCase().includes(q) ||
        (c.role || "").toLowerCase().includes(q) ||
        (c.agent_type || "").toLowerCase().includes(q),
    );
  }, [contacts, search]);

  const filteredRooms = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rooms;
    return rooms.filter(
      (t) =>
        (t.topic || "").toLowerCase().includes(q) ||
        (t.title || "").toLowerCase().includes(q),
    );
  }, [rooms, search]);

  const refreshContacts = useCallback(async () => {
    try {
      const [dms, meet] = await Promise.all([
        api.callingHubDms(),
        api.agentMeetings().catch(() => ({ proposals: [] })),
      ]);
      setContacts((dms.agents || []) as DmContact[]);
      setInvites((dms.invites || []) as HubInvite[]);
      setProposals((meet.proposals || []) as AgentMeetProposal[]);
      if (dms.user_name) setUserName(dms.user_name);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load chats");
    }
  }, []);

  const refreshRooms = useCallback(async () => {
    try {
      const data = await api.callingHubThreads();
      setRooms((data.threads || []) as LiveThread[]);
    } catch {
      /* optional tab */
    }
  }, []);

  const refreshSelected = useCallback(async (threadId: string) => {
    try {
      const data = await api.callingHubThread(threadId);
      setMessages((data.messages || []) as ThreadMsg[]);
      if (data.invites && data.is_dm && data.dm_agent === "ai_calling") {
        setInvites((data.invites || []) as HubInvite[]);
      }
      if (data.thread?.meta?.dm_agent || data.dm_agent) {
        const at = data.dm_agent || data.thread?.meta?.dm_agent;
        setSelectedAgent(at || null);
      }
    } catch {
      /* keep last snapshot */
    } finally {
      setLoadingChat(false);
    }
  }, []);

  useEffect(() => {
    void refreshContacts();
    const id = window.setInterval(() => void refreshContacts(), 2500);
    return () => window.clearInterval(id);
  }, [refreshContacts]);

  useEffect(() => {
    if (tab !== "rooms") return;
    void refreshRooms();
    const id = window.setInterval(() => void refreshRooms(), 2500);
    return () => window.clearInterval(id);
  }, [tab, refreshRooms]);

  useEffect(() => {
    if (!selectedId) return;
    setLoadingChat(true);
    void refreshSelected(selectedId);
    const id = window.setInterval(() => void refreshSelected(selectedId), 2500);
    return () => window.clearInterval(id);
  }, [selectedId, refreshSelected]);

  useEffect(() => {
    if (!stickToBottom.current) return;
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, selectedId]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!notifRef.current?.contains(e.target as Node)) setNotifOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function onChatScroll() {
    const el = chatScrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = dist < 72;
  }

  async function openAgentChat(contact: DmContact) {
    const agentType = contact.agent_type;
    if (!agentType || busy) return;
    setBusy(true);
    setError(null);
    setComposeHint(null);
    setActiveAgent(contact);
    setSelectedAgent(agentType);
    setMobileShowChat(true);
    stickToBottom.current = true;
    try {
      if (contact.dm_thread_id) {
        setSelectedId(contact.dm_thread_id);
        setLoadingChat(true);
        await refreshSelected(contact.dm_thread_id);
      } else {
        setLoadingChat(true);
        const res = await api.callingHubOpenDm(agentType);
        const tid = res.thread?.thread_id || res.thread_id;
        setSelectedId(tid);
        setMessages((res.messages || []) as ThreadMsg[]);
        if (res.agent) setActiveAgent({ ...contact, ...res.agent, dm_thread_id: tid });
        await refreshContacts();
      }
    } catch (e: any) {
      setError(e.message || "Could not open chat");
    } finally {
      setBusy(false);
      setLoadingChat(false);
    }
  }

  async function openRoom(thread: LiveThread) {
    setTab("rooms");
    setSelectedId(thread.thread_id);
    setSelectedAgent(null);
    setActiveAgent(null);
    setMobileShowChat(true);
    stickToBottom.current = true;
    setLoadingChat(true);
    await refreshSelected(thread.thread_id);
  }

  async function acceptInvite(inviteId: string) {
    setBusy(true);
    try {
      const res = await api.callingHubAcceptInvite(inviteId);
      setToast(
        res.message ||
          "Invite accepted — open AI Calling and Join with Marcus when ready.",
      );
      setNotifOpen(false);
      await refreshContacts();
      if (selectedId) await refreshSelected(selectedId);
    } catch (e: any) {
      setError(e.message || "Could not accept invite");
    } finally {
      setBusy(false);
    }
  }

  async function declineInvite(inviteId: string) {
    setBusy(true);
    try {
      await api.callingHubDeclineInvite(inviteId);
      await refreshContacts();
    } catch (e: any) {
      setError(e.message || "Could not decline");
    } finally {
      setBusy(false);
    }
  }

  async function approveAgentMeet(proposalId: string) {
    setBusy(true);
    try {
      const res = await api.agentMeetingApprove(proposalId);
      setToast(res.message || "Approved — watch live from AI Calling when ready.");
      setNotifOpen(false);
      await refreshContacts();
    } catch (e: any) {
      setError(e.message || "Could not approve");
    } finally {
      setBusy(false);
    }
  }

  async function requestCall() {
    if (!activeAgent?.name) return;
    setBusy(true);
    try {
      const query = `${activeAgent.name} (${activeAgent.role || activeAgent.agent_type || "specialist"})`;
      const res = await api.callingRequestPersonalMeeting(
        query,
        `I want to talk with ${activeAgent.name}`,
      );
      setToast(res.message || `Marcus requested ${activeAgent.name}.`);
      await refreshContacts();
      // Surface invite context in Marcus DM
      const opened = await api.callingHubOpenDm("ai_calling");
      const tid = opened.thread?.thread_id;
      if (tid) {
        setSelectedAgent("ai_calling");
        setActiveAgent({
          ...(opened.agent || { name: "Marcus", agent_type: "ai_calling" }),
          dm_thread_id: tid,
        });
        setSelectedId(tid);
        setMessages((opened.messages || []) as ThreadMsg[]);
        setMobileShowChat(true);
      }
    } catch (e: any) {
      setError(e.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendCompose(e: FormEvent) {
    e.preventDefault();
    const text = compose.trim();
    if (!text || busy || !selectedId) return;
    setBusy(true);
    setError(null);
    setComposeHint(null);
    try {
      const res = await api.callingHubCompose(text, selectedId);
      setCompose("");
      stickToBottom.current = true;
      const tid = res.thread_id || selectedId;
      if (tid && tid !== selectedId) setSelectedId(tid);
      if (tid) await refreshSelected(tid);
      await refreshContacts();
      if (res.routed === "postings") {
        setComposeHint("Mira drafted from this chat — optional: open Postings Studio.");
      } else if (res.routed === "agent_meet_propose" || res.routed === "agent_meet_approve") {
        setComposeHint(res.agent_meeting?.message || "Meeting updated.");
      } else if (res.routed === "external_meet") {
        setComposeHint(res.agent_meeting?.message || "External meet proxy started.");
      }
    } catch (err: any) {
      setError(err.message || "Could not send");
    } finally {
      setBusy(false);
    }
  }

  const headerAgent =
    activeAgent ||
    contacts.find((c) => c.agent_type === selectedAgent) ||
    null;
  const roomSelected =
    tab === "rooms" ? rooms.find((r) => r.thread_id === selectedId) : null;
  const statusLabel =
    headerAgent?.status === "working"
      ? "working"
      : headerAgent
        ? "online"
        : roomSelected
          ? "live room"
          : "";

  const placeholder = headerAgent?.agent_type === "posting_studio"
    ? 'Try: “create a post for Verdiq about …”'
    : headerAgent?.agent_type === "ai_calling"
      ? 'Try: “schedule a meeting with you” · “create a post…”'
      : headerAgent
        ? `Message ${headerAgent.name}…`
        : "Select a chat to message…";

  return (
    <AppShell
      title="Collaboration Hub"
      subtitle="Direct messages with your workforce"
      actions={
        <div className="ch-shell-actions">
          <div className="ch-notif" ref={notifRef}>
            <button
              type="button"
              className={`ch-notif-btn ${notifCount ? "has-badge" : ""}`}
              aria-label="Notifications"
              onClick={() => setNotifOpen((v) => !v)}
            >
              <span className="ch-bell" aria-hidden />
              {notifCount > 0 ? <span className="ch-notif-count">{notifCount}</span> : null}
            </button>
            {notifOpen ? (
              <div className="ch-notif-panel glass" role="menu">
                <p className="ch-label">Updates</p>
                {pending.length === 0 && openProposals.length === 0 ? (
                  <p className="muted ch-notif-empty">No pending invites</p>
                ) : null}
                {pending.map((inv) => (
                  <div key={inv.invite_id} className="ch-notif-row">
                    <p>
                      <strong>{inv.invited_by?.name || "Agent"}</strong>
                      {" — "}
                      {(inv.message || "Meeting invite").slice(0, 90)}
                    </p>
                    <div className="ch-notif-actions">
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={busy}
                        onClick={() => void acceptInvite(inv.invite_id)}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busy}
                        onClick={() => void declineInvite(inv.invite_id)}
                      >
                        Decline
                      </button>
                    </div>
                  </div>
                ))}
                {openProposals.map((p) => (
                  <div key={p.proposal_id} className="ch-notif-row">
                    <p>
                      <strong>
                        {(p.proposer?.name || "Agent") + " → " + (p.invitee?.name || "Agent")}
                      </strong>
                      {" · "}
                      {p.status}
                      {p.topic ? ` — ${p.topic}` : ""}
                    </p>
                    <div className="ch-notif-actions">
                      {p.status === "proposed" ? (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={busy}
                          onClick={() => void approveAgentMeet(p.proposal_id)}
                        >
                          Approve
                        </button>
                      ) : null}
                      {(p.status === "approved" || p.status === "live") && (
                        <Link
                          className="btn btn-ghost btn-sm"
                          to={`/dashboard/calling?agentMeet=${encodeURIComponent(p.proposal_id)}&spectator=1`}
                          onClick={() => setNotifOpen(false)}
                        >
                          Watch
                        </Link>
                      )}
                    </div>
                  </div>
                ))}
                <Link
                  className="text-link ch-notif-link"
                  to="/dashboard/calling"
                  onClick={() => setNotifOpen(false)}
                >
                  Open AI Calling
                </Link>
              </div>
            ) : null}
          </div>
          <Link className="btn btn-ghost btn-sm" to="/dashboard/calling">
            AI Calling
          </Link>
        </div>
      }
    >
      <div className={`ch ch-wa ${mobileShowChat ? "is-chat-open" : ""}`}>
        {error ? <div className="banner error ch-banner">{error}</div> : null}
        {toast ? (
          <div className="ch-toast" role="status">
            <p>{toast}</p>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToast(null)}>
              Dismiss
            </button>
          </div>
        ) : null}

        <div className="ch-workspace ch-wa-workspace">
          <aside className="ch-rail glass ch-wa-rail" aria-label="Chats">
            <header className="ch-rail-head ch-wa-rail-head">
              <div className="ch-wa-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  className={`ch-wa-tab ${tab === "dms" ? "is-active" : ""}`}
                  aria-selected={tab === "dms"}
                  onClick={() => setTab("dms")}
                >
                  Chats
                </button>
                <button
                  type="button"
                  role="tab"
                  className={`ch-wa-tab ${tab === "rooms" ? "is-active" : ""}`}
                  aria-selected={tab === "rooms"}
                  onClick={() => setTab("rooms")}
                >
                  Rooms
                </button>
              </div>
              <label className="ch-wa-search">
                <span className="sr-only">Search</span>
                <input
                  className="field"
                  placeholder={tab === "dms" ? "Search agents…" : "Search rooms…"}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoComplete="off"
                />
              </label>
            </header>

            {tab === "dms" ? (
              filteredContacts.length === 0 ? (
                <div className="ch-empty">
                  <p className="ch-empty-title">No agents</p>
                  <p className="muted">Workforce contacts will appear here.</p>
                </div>
              ) : (
                <ul className="ch-thread-list ch-wa-list">
                  {filteredContacts.map((c) => {
                    const active =
                      selectedAgent === c.agent_type ||
                      (!!c.dm_thread_id && c.dm_thread_id === selectedId);
                    return (
                      <li key={c.agent_type || c.name}>
                        <button
                          type="button"
                          className={`ch-thread ch-wa-contact ${active ? "is-active" : ""}`}
                          onClick={() => void openAgentChat(c)}
                        >
                          <div className="ch-thread-av">
                            <AgentAvatar {...AvatarProps(c)} size={44} />
                            <span
                              className={`ch-status-dot ${c.status === "working" ? "is-working" : ""}`}
                              title={c.status || "online"}
                            />
                          </div>
                          <div className="ch-thread-main">
                            <div className="ch-thread-top">
                              <span className="ch-thread-name">{c.name}</span>
                              <span className="ch-thread-time">{formatTime(c.updated_at)}</span>
                            </div>
                            <p className="ch-wa-role">{c.role}</p>
                            <div className="ch-wa-preview-row">
                              <p className="ch-thread-preview">
                                {c.preview || "Tap to start chatting"}
                              </p>
                              {c.unread && c.unread > 0 ? (
                                <span className="ch-unread">{c.unread > 9 ? "9+" : c.unread}</span>
                              ) : null}
                            </div>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )
            ) : filteredRooms.length === 0 ? (
              <div className="ch-empty">
                <p className="ch-empty-title">No rooms</p>
                <p className="muted">Optional swarm rooms appear here.</p>
              </div>
            ) : (
              <ul className="ch-thread-list ch-wa-list">
                {filteredRooms.map((t) => {
                  const active = selectedId === t.thread_id && !selectedAgent;
                  const lead = (t.participants || [])[0];
                  return (
                    <li key={t.thread_id}>
                      <button
                        type="button"
                        className={`ch-thread ch-wa-contact ${active ? "is-active" : ""}`}
                        onClick={() => void openRoom(t)}
                      >
                        <div className="ch-thread-av">
                          {lead ? (
                            <AgentAvatar {...AvatarProps(lead)} size={44} />
                          ) : (
                            <span className="ch-av-fallback ch-av-lg" />
                          )}
                          <span className="ch-status-dot" title="Live" />
                        </div>
                        <div className="ch-thread-main">
                          <div className="ch-thread-top">
                            <span className="ch-thread-name">{t.topic || t.title}</span>
                            <span className="ch-thread-time">{formatTime(t.updated_at)}</span>
                          </div>
                          <p className="ch-thread-preview">{t.preview || "Working room"}</p>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>

          <section className="ch-main glass ch-wa-main" aria-live="polite">
            {selectedId && (headerAgent || roomSelected) ? (
              <>
                <header className="ch-main-head ch-wa-head">
                  <button
                    type="button"
                    className="ch-wa-back"
                    aria-label="Back to chats"
                    onClick={() => setMobileShowChat(false)}
                  >
                    ←
                  </button>
                  {headerAgent ? (
                    <AgentAvatar {...AvatarProps(headerAgent)} size={40} />
                  ) : (
                    <span className="ch-av-fallback ch-av-lg" />
                  )}
                  <div className="ch-wa-head-meta">
                    <h2 className="ch-room-title">
                      {headerAgent?.name || roomSelected?.topic || "Chat"}
                    </h2>
                    <p className="ch-wa-status">
                      {headerAgent?.role ? <span>{headerAgent.role}</span> : null}
                      {statusLabel ? (
                        <>
                          {headerAgent?.role ? <span className="ch-dot-sep">·</span> : null}
                          <span className={`ch-online ${statusLabel === "working" ? "is-working" : ""}`}>
                            {statusLabel}
                          </span>
                        </>
                      ) : null}
                    </p>
                  </div>
                  <div className="ch-wa-head-actions">
                    {headerAgent ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() => void requestCall()}
                        >
                          Request call
                        </button>
                        <Link className="btn btn-ghost btn-sm" to="/dashboard/calling">
                          Schedule
                        </Link>
                      </>
                    ) : (
                      <Link className="btn btn-ghost btn-sm" to="/dashboard/calling">
                        AI Calling
                      </Link>
                    )}
                  </div>
                </header>

                <div
                  ref={chatScrollRef}
                  className="ch-messages ch-wa-messages"
                  role="log"
                  onScroll={onChatScroll}
                >
                  {loadingChat && messages.length === 0 ? (
                    <div className="ch-empty ch-empty-center">
                      <p className="ch-empty-title">Loading chat</p>
                      <p className="muted">Fetching messages…</p>
                    </div>
                  ) : messages.length === 0 ? (
                    <div className="ch-empty ch-empty-center">
                      <p className="ch-empty-title">Say hello</p>
                      <p className="muted">
                        {headerAgent
                          ? `Start a conversation with ${headerAgent.name}.`
                          : "Messages will appear here."}
                      </p>
                    </div>
                  ) : (
                    messages.map((m) => {
                      const mine = isUserMessage(m, userName);
                      const isSystem = m.kind === "system" || m.kind === "invite";
                      if (isSystem) {
                        return (
                          <div key={m.message_id} className="ch-wa-system">
                            <p>{m.body}</p>
                            <time>{formatTime(m.created_at)}</time>
                          </div>
                        );
                      }
                      return (
                        <article
                          key={m.message_id}
                          className={`ch-wa-bubble-row ${mine ? "is-mine" : "is-theirs"}`}
                        >
                          {!mine ? (
                            <div className="ch-wa-bubble-av">
                              <AgentAvatar
                                {...AvatarProps(
                                  m.avatar ||
                                    headerAgent || { name: m.sender_name || "A", agent_type: m.agent_id },
                                )}
                                size={28}
                              />
                            </div>
                          ) : null}
                          <div className={`ch-wa-bubble ${mine ? "mine" : "theirs"}`}>
                            {!mine ? (
                              <span className="ch-wa-bubble-name">
                                {m.sender_name || m.agent_id || "Agent"}
                              </span>
                            ) : null}
                            <p className="ch-wa-bubble-text">{m.body}</p>
                            <time className="ch-wa-bubble-time">{formatTime(m.created_at)}</time>
                            {(m.sender_name === "Mira" ||
                              m.agent_id === "posting_studio" ||
                              (m.body || "").includes("Mira (Postings)")) && (
                              <p className="ch-msg-links">
                                <Link className="text-link" to="/dashboard/postings">
                                  Open in Postings
                                </Link>
                              </p>
                            )}
                          </div>
                        </article>
                      );
                    })
                  )}

                  {/* Compact invite chips inside Marcus chat */}
                  {headerAgent?.agent_type === "ai_calling" && pending.length > 0
                    ? pending.map((inv) => (
                        <div key={`inline-${inv.invite_id}`} className="ch-wa-invite-card">
                          <p>
                            <strong>Meeting invite</strong> from{" "}
                            {inv.invited_by?.name || "an agent"}
                          </p>
                          <p className="muted">{(inv.message || "").slice(0, 140)}</p>
                          <div className="ch-notif-actions">
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              disabled={busy}
                              onClick={() => void acceptInvite(inv.invite_id)}
                            >
                              Accept
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy}
                              onClick={() => void declineInvite(inv.invite_id)}
                            >
                              Decline
                            </button>
                          </div>
                        </div>
                      ))
                    : null}

                  <div ref={chatEndRef} />
                </div>

                <footer className="ch-compose ch-wa-compose">
                  {composeHint ? <p className="ch-compose-hint muted">{composeHint}</p> : null}
                  <form className="ch-compose-form" onSubmit={(e) => void sendCompose(e)}>
                    <input
                      className="field"
                      placeholder={placeholder}
                      value={compose}
                      onChange={(e) => setCompose(e.target.value)}
                      disabled={busy || (!headerAgent && !!roomSelected)}
                      autoComplete="off"
                    />
                    <button
                      className="btn btn-primary"
                      type="submit"
                      disabled={busy || !compose.trim() || (!headerAgent && !!roomSelected)}
                    >
                      Send
                    </button>
                  </form>
                  {roomSelected && !headerAgent ? (
                    <p className="ch-compose-foot muted">
                      Rooms are observe-first — open an agent chat to talk 1:1.
                    </p>
                  ) : null}
                </footer>
              </>
            ) : (
              <div className="ch-empty ch-empty-center ch-wa-empty">
                <p className="ch-empty-title">Select a chat</p>
                <p className="muted">
                  Open Aurelia, Marcus, Mira, or any agent — each has a private thread.
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
