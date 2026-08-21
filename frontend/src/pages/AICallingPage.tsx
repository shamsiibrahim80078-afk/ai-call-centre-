import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AppShell, { AgentAvatar } from "../components/AppShell";
import LiveKitMeetingRoom, {
  type AgentPresencePayload,
  type DialogueTurn,
  type MeetingParticipant,
} from "../components/LiveKitMeetingRoom";
import { api } from "../api/client";

type Meeting = {
  meeting_id: string;
  topic: string;
  status: string;
  scheduled_at_pkt?: string;
  scheduled_at_utc?: string;
  livekit_room?: string;
  join_gate_status?: string;
  participants?: MeetingParticipant[];
  agenda?: string[];
  call_window_open?: boolean;
  call_window_sec?: number;
  telegram_announce?: { status?: string; message?: string; join_url?: string };
};

type TimedSession = {
  session_id: string;
  purpose?: string;
  status: string;
  allowed_seconds?: number;
  consumed_seconds?: number;
  created_at?: string;
  started_at?: string;
  ended_at?: string;
};

/** Client-side fallback if API omits call_window_open (±5 min Asia/Karachi scheduled time). */
function isInCallWindow(m: Meeting, nowMs = Date.now()): boolean {
  if (m.call_window_open === true) return true;
  if (m.status === "live") return true;
  if (m.status !== "scheduled") return false;
  const raw = m.scheduled_at_utc || m.scheduled_at_pkt;
  if (!raw) return false;
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return false;
  const windowMs = (m.call_window_sec ?? 300) * 1000;
  return Math.abs(nowMs - t) <= windowMs;
}

function defaultPktLocalInput(): string {
  // Rough PKT = UTC+5 for the schedule form default (now + 2 min)
  const d = new Date(Date.now() + 2 * 60 * 1000 + 5 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function apiBase(): string {
  return (import.meta as any).env?.VITE_API_BASE || "";
}

function absolutizeAudioUrl(path?: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${apiBase()}${path}`;
}

export default function AICallingPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [timedSessions, setTimedSessions] = useState<TimedSession[]>([]);
  const [budget, setBudget] = useState<{
    remaining_seconds?: number;
    per_call_max_seconds?: number;
    daily_budget_seconds?: number;
    can_start_call?: boolean;
    usage_day?: string;
    status?: string;
    message?: string;
  } | null>(null);
  const [activeMeeting, setActiveMeeting] = useState<Meeting | null>(null);
  const [livekitReady, setLivekitReady] = useState<boolean | null>(null);
  const [livekitMsg, setLivekitMsg] = useState<string | null>(null);
  const [agoraMode, setAgoraMode] = useState<string | null>(null);
  const [agoraMsg, setAgoraMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"lobby" | "live">("lobby");
  const [tokenPayload, setTokenPayload] = useState<{ token: string; url: string } | null>(null);
  const [agentPresence, setAgentPresence] = useState<AgentPresencePayload | null>(null);
  const [multiAgentPresence, setMultiAgentPresence] = useState<AgentPresencePayload[] | null>(null);
  const [dialogueTurns, setDialogueTurns] = useState<DialogueTurn[] | null>(null);
  const [spectatorMode, setSpectatorMode] = useState(false);
  const [agentMeetId, setAgentMeetId] = useState<string | null>(() => searchParams.get("agentMeet"));
  const [agentMeetProposal, setAgentMeetProposal] = useState<any | null>(null);
  const [inviteAgentType, setInviteAgentType] = useState("marketing_manager");
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [workChat, setWorkChat] = useState<{ sender_name?: string; body: string; message_id?: string }[]>([]);
  const [workInput, setWorkInput] = useState("");
  const [interactName, setInteractName] = useState(() => searchParams.get("request") || "");
  const [interactNote, setInteractNote] = useState<string | null>(null);
  const [scheduleTopic, setScheduleTopic] = useState("Working session with Marcus");
  const [scheduleWhen, setScheduleWhen] = useState(defaultPktLocalInput);
  const [scheduleNote, setScheduleNote] = useState<string | null>(null);
  const deepLinkMeeting = searchParams.get("meeting");
  const deepLinkAgentMeet = searchParams.get("agentMeet");
  const wantSpectator = searchParams.get("spectator") === "1";
  const autoConnectingRef = useRef<string | null>(null);
  const budgetActivatedRef = useRef(false);
  const agentMeetWatchRef = useRef<string | null>(null);

  useEffect(() => {
    const req = searchParams.get("request");
    if (req) setInteractName(req);
    if (deepLinkAgentMeet) setAgentMeetId(deepLinkAgentMeet);
  }, [searchParams, deepLinkAgentMeet]);

  const refreshAgentMeet = useCallback(async (pid: string) => {
    try {
      const bundle = await api.agentMeeting(pid);
      setAgentMeetProposal(bundle.proposal || null);
      return bundle;
    } catch {
      return null;
    }
  }, []);

  const watchAgentMeet = useCallback(
    async (pid: string) => {
      if (agentMeetWatchRef.current === pid && tokenPayload) return;
      agentMeetWatchRef.current = pid;
      setBusy(true);
      setError(null);
      try {
        let bundle = await api.agentMeeting(pid);
        setAgentMeetProposal(bundle.proposal || null);
        if (bundle.proposal?.status === "approved") {
          // Poll until live or force-start if countdown already 0
          if ((bundle.proposal.countdown_remaining_seconds ?? 1) <= 0) {
            bundle = await api.agentMeetingStart(pid, false);
          }
        }
        if (bundle.proposal?.status !== "live" && bundle.status !== "live") {
          setView("live");
          setSpectatorMode(true);
          setError(null);
          return;
        }
        const spec = await api.agentMeetingSpectator(pid, "Spectator");
        if (spec.token && spec.url) {
          setTokenPayload({ token: spec.token, url: spec.url });
          setSpectatorMode(true);
          const agentsTok = (spec.agent_tokens || bundle.agent_tokens || []) as any[];
          setMultiAgentPresence(
            agentsTok
              .filter((t) => t?.token && t?.url)
              .map((t) => ({
                token: t.token,
                url: t.url,
                identity: t.identity,
                name: t.name || t.agent?.name,
                agentType: t.agent_type,
                agent: t.agent || null,
              })),
          );
          const dlg = (spec.dialogue || bundle.dialogue || []) as any[];
          setDialogueTurns(
            dlg.map((d) => ({
              agent_type: d.agent_type,
              name: d.name,
              text: d.text,
              audioUrl: absolutizeAudioUrl(d.audio_url),
            })),
          );
          if (spec.meeting) setActiveMeeting(spec.meeting as Meeting);
          else if (bundle.proposal?.meeting_id) {
            try {
              const m = await api.callingMeeting(bundle.proposal.meeting_id);
              setActiveMeeting(m);
            } catch {
              /* ignore */
            }
          }
          setAgentPresence(null);
          setView("live");
          setSearchParams({ agentMeet: pid, spectator: "1" });
        }
      } catch (err: any) {
        agentMeetWatchRef.current = null;
        setError(err.message || "Could not watch agent meeting");
      } finally {
        setBusy(false);
      }
    },
    [setSearchParams, tokenPayload],
  );

  useEffect(() => {
    if (!deepLinkAgentMeet || !wantSpectator) return;
    void watchAgentMeet(deepLinkAgentMeet);
  }, [deepLinkAgentMeet, wantSpectator, watchAgentMeet]);

  useEffect(() => {
    if (!agentMeetId) return;
    void refreshAgentMeet(agentMeetId);
    const id = window.setInterval(() => {
      void refreshAgentMeet(agentMeetId).then((b) => {
        if (b?.proposal?.status === "live" && wantSpectator && !tokenPayload) {
          void watchAgentMeet(agentMeetId);
        }
      });
    }, 2000);
    return () => window.clearInterval(id);
  }, [agentMeetId, refreshAgentMeet, wantSpectator, tokenPayload, watchAgentMeet]);

  const refresh = useCallback(async () => {
    try {
      const [hub, list, timed, bud] = await Promise.all([
        api.callingHub(),
        api.callingMeetings(),
        api.callingTimedSessions({ limit: 20 }).catch(() => ({ sessions: [] })),
        api.callingBudget().catch(() => null),
      ]);
      setLivekitReady(Boolean(hub.livekit?.configured));
      setLivekitMsg(hub.livekit?.message || null);
      setAgoraMode(hub.agora?.mode || null);
      setAgoraMsg(hub.agora?.message || null);
      setMeetings(list.meetings || []);
      setTimedSessions(timed.sessions || []);
      if (bud) setBudget(bud);
      const active = hub.active_meeting as Meeting | null;
      if (deepLinkMeeting) {
        try {
          const m = await api.callingMeeting(deepLinkMeeting);
          setActiveMeeting(m);
        } catch {
          if (active) setActiveMeeting(active);
        }
      } else if (active) {
        setActiveMeeting(active);
      }
      const mid = deepLinkMeeting || active?.meeting_id;
      if (mid && Array.isArray(hub.messages)) {
        setWorkChat(
          (hub.messages as any[])
            .filter((m) => m.meeting_id === mid)
            .map((m) => ({
              message_id: m.message_id,
              sender_name: m.sender_name,
              body: m.body,
            })),
        );
      }
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load calling lobby");
    }
  }, [deepLinkMeeting]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);

  const joinable = useMemo(
    () => meetings.filter((m) => isInCallWindow(m, nowTick)),
    [meetings, nowTick],
  );

  const upcoming = useMemo(
    () => meetings.filter((m) => !isInCallWindow(m, nowTick) && m.status === "scheduled"),
    [meetings, nowTick],
  );

  const activeJoinable = activeMeeting ? isInCallWindow(activeMeeting, nowTick) : false;

  const inviteAdmitted = Boolean(
    activeMeeting?.status === "live" && activeMeeting?.join_gate_status === "admitted",
  );

  const applyEnterResult = useCallback(
    (res: any, meetingFallback?: Meeting | null) => {
      const meeting = (res.meeting as Meeting) || meetingFallback || null;
      if (meeting) setActiveMeeting(meeting);
      const ut = res.user_token;
      if (ut?.token && ut?.url) {
        setTokenPayload({ token: ut.token, url: ut.url });
      }
      const ap = res.agent_presence;
      const tok = ap?.token;
      if (tok?.token && tok?.url) {
        setAgentPresence({
          token: tok.token,
          url: tok.url,
          identity: tok.identity,
          name: tok.name || ap?.agent?.name,
          audioUrl: absolutizeAudioUrl(ap?.greeting?.audio_url),
          greetingScript: ap?.greeting?.script || null,
          agent: ap?.agent || null,
          maxCallSeconds: ap?.max_call_seconds,
          timedSessionId: ap?.timed_session_id || ap?.timed?.session?.session_id || null,
        });
      } else {
        setAgentPresence(null);
      }
      if (ap?.budget) setBudget(ap.budget);
      setView("live");
      if (meeting?.meeting_id) setSearchParams({ meeting: meeting.meeting_id });
    },
    [setSearchParams],
  );

  const enterMeeting = useCallback(
    async (id: string) => {
      if (autoConnectingRef.current === id && tokenPayload) return;
      autoConnectingRef.current = id;
      setBusy(true);
      setError(null);
      try {
        if (livekitReady === false) {
          setError(
            livekitMsg ||
              "LiveKit credentials missing — set VERIDIQ_LIVEKIT_URL / API_KEY / API_SECRET. You can still schedule meetings below.",
          );
          autoConnectingRef.current = null;
          return;
        }
        const res = await api.callingMeetingEnter(id, {
          identity: `user-${Date.now().toString(36)}`,
          name: "You",
        });
        applyEnterResult(res);
      } catch (err: any) {
        autoConnectingRef.current = null;
        setError(err.message || "Could not enter meeting — check LiveKit credentials");
      } finally {
        setBusy(false);
      }
    },
    [applyEnterResult, livekitMsg, livekitReady, tokenPayload],
  );

  // Deep-link from invite accept: show live lobby for that meeting — do NOT auto-connect.
  // User must click Join with Marcus / Meet Marcus now.
  useEffect(() => {
    if (!activeMeeting) return;
    if (activeMeeting.status !== "live") return;
    if (activeMeeting.join_gate_status !== "admitted") return;
    if (!tokenPayload) setView("live");
  }, [activeMeeting?.meeting_id, activeMeeting?.status, activeMeeting?.join_gate_status, tokenPayload]);

  async function resetBudget() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.callingBudgetReset();
      setBudget(res);
      setScheduleNote(res.message || "Calling budget reset for today (UTC).");
      await refresh();
    } catch (err: any) {
      setError(err.message || "Budget reset failed");
    } finally {
      setBusy(false);
    }
  }

  async function requestInteractViaMarcus(e: FormEvent) {
    e.preventDefault();
    const who = interactName.trim();
    if (!who || busy) return;
    setBusy(true);
    setError(null);
    setInteractNote(null);
    try {
      const cmd = await api.callingAgentCommand(`I want to interact with ${who}`);
      if (cmd.intent === "request_personal_meeting" || cmd.action?.action === "request_personal_meeting") {
        setInteractNote(cmd.reply || cmd.action?.message || "Request posted — check Collaboration Hub for the invite.");
      } else {
        const res = await api.callingRequestPersonalMeeting(who, `I want to interact with ${who}`);
        setInteractNote(res.message || "Marcus posted a personal-meeting request in the hub.");
      }
      await refresh();
    } catch (err: any) {
      setError(err.message || "Could not request interact");
    } finally {
      setBusy(false);
    }
  }

  async function scheduleMeetingForm(e: FormEvent) {
    e.preventDefault();
    if (!scheduleTopic.trim() || busy) return;
    setBusy(true);
    setError(null);
    setScheduleNote(null);
    try {
      const res = await api.callingScheduleMeeting({
        topic: scheduleTopic.trim(),
        scheduled_at_pkt: scheduleWhen,
        agenda: ["Greeting", "Agenda check-in", "Next steps"],
        agent_types: ["ai_calling", "ceo"],
      });
      if (!res.ok) throw new Error(res.message || res.error || "Schedule failed");
      setScheduleNote(
        `Scheduled “${res.meeting?.topic}” for ${res.meeting?.scheduled_at_pkt || scheduleWhen} PKT.`,
      );
      // Also mirror a timed budget reservation
      try {
        await api.callingScheduleTimed({
          purpose: scheduleTopic.trim(),
          requested_seconds: budget?.per_call_max_seconds || 120,
          auto_start: false,
        });
      } catch {
        /* optional */
      }
      await refresh();
    } catch (err: any) {
      setError(err.message || "Could not schedule meeting");
    } finally {
      setBusy(false);
    }
  }

  async function meetMarcusNow() {
    setBusy(true);
    setError(null);
    setScheduleNote(null);
    try {
      const res = await api.callingMeetingQuick({
        topic: scheduleTopic.trim() || "Timed call with Marcus",
        agenda: ["Greeting", "Agenda check-in", "Next steps"],
        name: "You",
      });
      if (res.error === "livekit_not_configured") {
        setLivekitReady(false);
        setLivekitMsg(res.livekit?.message || res.message);
        setScheduleNote(res.message || "Meeting saved — configure LiveKit to go live.");
        if (res.scheduled?.meeting) setActiveMeeting(res.scheduled.meeting);
        await refresh();
        return;
      }
      if (!res.ok) throw new Error(res.message || res.error || "Quick meet failed");
      applyEnterResult(res);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Could not start meeting with Marcus");
    } finally {
      setBusy(false);
    }
  }

  async function startMeeting(id: string) {
    setBusy(true);
    setError(null);
    try {
      if (livekitReady === false) {
        setError(livekitMsg || "LiveKit must be configured before starting a live call.");
        return;
      }
      await enterMeeting(id);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Start failed — LiveKit must be configured");
    } finally {
      setBusy(false);
    }
  }

  async function requestJoin(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.callingRequestJoin(id);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Request join failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmJoin(id: string, yes: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (yes) {
        await enterMeeting(id);
      } else {
        await api.callingConfirmJoin(id, false);
      }
      await refresh();
    } catch (err: any) {
      setError(err.message || "Confirm join failed");
    } finally {
      setBusy(false);
    }
  }

  async function endMeeting(id: string) {
    setBusy(true);
    try {
      await api.callingEndMeeting(id);
      setTokenPayload(null);
      setAgentPresence(null);
      autoConnectingRef.current = null;
      setView("lobby");
      setSearchParams({});
      await refresh();
    } catch (err: any) {
      setError(err.message || "End failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendWorkChat(e: FormEvent) {
    e.preventDefault();
    const text = workInput.trim();
    if (!text || !activeMeeting || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.callingHubMessage(text, activeMeeting.meeting_id);
      setWorkInput("");
      const next = [...workChat];
      if (res.message) next.push({ message_id: res.message.message_id, sender_name: "You", body: res.message.body });
      if (res.reply) next.push({ message_id: res.reply.message_id, sender_name: res.reply.sender_name, body: res.reply.body });
      setWorkChat(next);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Work chat failed");
    } finally {
      setBusy(false);
    }
  }

  const gate = activeMeeting?.join_gate_status || "closed";
  const agents = useMemo(() => {
    const fromMeet = (agentMeetProposal?.participants as MeetingParticipant[]) || [];
    const base = (fromMeet.length
      ? fromMeet
      : ((activeMeeting?.participants as MeetingParticipant[]) || [])
    ).slice();
    if (!base.some((a) => a.agent_type === "ai_calling")) {
      base.unshift({
        agent_type: "ai_calling",
        name: "Marcus",
        role: "AI Calling Coordinator",
        avatar_hue: 18,
        avatar_presentation: "masculine",
        avatar_hair: "fade",
        avatar_skin: "#c68642",
        avatar_hair_color: "#1a120c",
        kind: "agent",
      });
    }
    return base;
  }, [activeMeeting, agentMeetProposal]);

  const showLiveControls =
    (view === "live" && activeMeeting && (activeJoinable || inviteAdmitted)) ||
    (view === "live" && Boolean(agentMeetId && (tokenPayload || agentMeetProposal)));

  async function inviteAgentToCall() {
    if (!agentMeetId || !inviteAgentType.trim()) return;
    setBusy(true);
    try {
      const res = await api.agentMeetingInviteAgent(agentMeetId, inviteAgentType.trim());
      setAgentMeetProposal(res.proposal || agentMeetProposal);
      if (res.extra_turn?.audio_url) {
        setDialogueTurns((prev) => [
          ...(prev || []),
          {
            agent_type: res.extra_turn.agent_type,
            name: res.extra_turn.name,
            text: res.extra_turn.text,
            audioUrl: absolutizeAudioUrl(res.extra_turn.audio_url),
          },
        ]);
      }
      if (res.agent_tokens) {
        setMultiAgentPresence(
          (res.agent_tokens as any[])
            .filter((t) => t?.token && t?.url)
            .map((t) => ({
              token: t.token,
              url: t.url,
              identity: t.identity,
              name: t.name || t.agent?.name,
              agentType: t.agent_type,
              agent: t.agent || null,
            })),
        );
      }
      setScheduleNote(res.message || `Extended to ${res.max_duration_seconds || 300}s`);
    } catch (e: any) {
      setError(e.message || "Invite failed");
    } finally {
      setBusy(false);
    }
  }

  async function extendAgentCall() {
    if (!agentMeetId) return;
    setBusy(true);
    try {
      const res = await api.agentMeetingExtend(agentMeetId);
      setAgentMeetProposal(res.proposal || agentMeetProposal);
      setScheduleNote(res.message || "Extended to 5 minutes");
    } catch (e: any) {
      setError(e.message || "Extend failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      title="AI Calling"
      subtitle="Meet Marcus live — schedule, join, hear the agent on the other side"
      actions={
        <div className="calling-actions">
          <button
            type="button"
            className={`btn btn-ghost btn-sm ${view === "lobby" ? "is-active" : ""}`}
            onClick={() => setView("lobby")}
          >
            Lobby
          </button>
          <button
            type="button"
            className={`btn btn-ghost btn-sm ${view === "live" ? "is-active" : ""}`}
            onClick={() => setView("live")}
            disabled={!activeMeeting || activeMeeting.status !== "live" || (!activeJoinable && !inviteAdmitted)}
          >
            Live room
          </button>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}

      <div className="meet-status-row">
        {livekitReady ? (
          <span className="pill ok">LiveKit configured</span>
        ) : livekitReady === false ? (
          <span className="pill warn">LiveKit credentials missing</span>
        ) : (
          <span className="pill">Checking LiveKit…</span>
        )}
        {budget ? (
          <span className={`pill ${budget.can_start_call === false ? "warn" : ""}`}>
            Budget {Math.round(budget.remaining_seconds ?? 0)}s left · max{" "}
            {budget.per_call_max_seconds ?? 120}s/call
            {budget.usage_day ? ` · UTC ${budget.usage_day}` : ""}
          </span>
        ) : null}
        {agoraMode === "rtc_ready" ? <span className="pill ok">Agora RTC ready</span> : null}
        {activeMeeting?.status === "live" && activeJoinable ? <span className="pill ok">Meeting live</span> : null}
        {livekitMsg ? <span className="muted meet-lk-note">{livekitMsg}</span> : null}
        {agoraMsg && agoraMode === "agent_ids_only" ? (
          <span className="muted meet-lk-note">{agoraMsg}</span>
        ) : null}
      </div>

      {budget?.can_start_call === false ? (
        <div className="banner warn" style={{ marginBottom: "1rem" }}>
          Daily calling budget exhausted — resets at UTC midnight
          {budget.usage_day ? ` (day ${budget.usage_day})` : ""}. You can still open the lobby; Marcus
          join is allowed, but the timed cap may be disabled until budget resets.{" "}
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void resetBudget()}>
            Reset budget (dev)
          </button>{" "}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setView("lobby")}>
            Open lobby
          </button>
        </div>
      ) : null}

      {agentMeetProposal ? (
        <div className="banner" style={{ marginBottom: "1rem" }} role="status">
          <strong>Agent meeting</strong> · {agentMeetProposal.status}
          {agentMeetProposal.status === "approved" &&
          agentMeetProposal.countdown_remaining_seconds != null ? (
            <> · joins in {agentMeetProposal.countdown_remaining_seconds}s</>
          ) : null}
          {agentMeetProposal.max_duration_seconds ? (
            <> · budget {agentMeetProposal.max_duration_seconds}s</>
          ) : null}
          {agentMeetProposal.status === "live" && !tokenPayload ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              style={{ marginLeft: "0.75rem" }}
              disabled={busy}
              onClick={() => agentMeetId && void watchAgentMeet(agentMeetId)}
            >
              Join as spectator
            </button>
          ) : null}
          {agentMeetProposal.status === "approved" ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ marginLeft: "0.75rem" }}
              disabled={busy}
              onClick={() => agentMeetId && void api.agentMeetingStart(agentMeetId, true).then(() => watchAgentMeet(agentMeetId))}
            >
              Force start (dev)
            </button>
          ) : null}
        </div>
      ) : null}

      {livekitReady === false ? (
        <div className="banner warn" style={{ marginBottom: "1rem" }}>
          Live voice meetings need LiveKit. Set <code>VERIDIQ_LIVEKIT_URL</code>,{" "}
          <code>VERIDIQ_LIVEKIT_API_KEY</code>, and <code>VERIDIQ_LIVEKIT_API_SECRET</code> in{" "}
          <code>.env</code>, then restart the API. You can still schedule meetings and review timed-call
          budgets below.
        </div>
      ) : null}

      {view === "lobby" ? (
        <div className="meet-side" style={{ maxWidth: 760 }}>
          <form className="meet-schedule" onSubmit={(e) => void scheduleMeetingForm(e)}>
            <h3>Schedule a meeting</h3>
            <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
              Pick a topic and Asia/Karachi time, or start a live call with Marcus now (greeting + agenda,
              timed budget).
            </p>
            <label className="meet-label">
              Topic
              <input
                className="field"
                value={scheduleTopic}
                onChange={(e) => setScheduleTopic(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="meet-label">
              Date / time (PKT)
              <input
                className="field"
                type="datetime-local"
                value={scheduleWhen}
                onChange={(e) => setScheduleWhen(e.target.value)}
                disabled={busy}
              />
            </label>
            <div className="meet-card-actions" style={{ marginTop: "0.75rem" }}>
              <button className="btn btn-ghost" type="submit" disabled={busy || !scheduleTopic.trim()}>
                Save schedule
              </button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={busy}
                onClick={() => void meetMarcusNow()}
              >
                Meet Marcus now
              </button>
            </div>
            {scheduleNote ? <p className="muted" style={{ marginTop: "0.5rem" }}>{scheduleNote}</p> : null}
          </form>

          <form className="meet-schedule hub-request-interact" onSubmit={(e) => void requestInteractViaMarcus(e)}>
            <h3>Request interact (via Marcus)</h3>
            <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
              Saw someone in the Collaboration Hub? Name them — Marcus requests approval, then you accept the
              invite and join LiveKit.
            </p>
            <label className="meet-label">
              Agent name or role
              <input
                className="field"
                placeholder="e.g. Adrian, Canva / daily posts, Lena…"
                value={interactName}
                onChange={(e) => setInteractName(e.target.value)}
                disabled={busy}
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={busy || !interactName.trim()}>
              Ask Marcus to arrange meeting
            </button>
            {interactNote ? <p className="muted" style={{ marginTop: "0.5rem" }}>{interactNote}</p> : null}
          </form>

          <div className="meet-list" style={{ marginTop: "1.25rem" }}>
            <h3>Joinable now</h3>
            {joinable.length === 0 ? (
              <div className="calling-idle" style={{ marginTop: "0.75rem" }}>
                <p className="calling-eyebrow">No active call window</p>
                <h2 className="calling-hero-title">Waiting for a live meeting</h2>
                <p className="calling-lede muted">
                  Use <strong>Meet Marcus now</strong>, accept a Collaboration Hub invite, or wait for a
                  scheduled PKT window (±5 min).
                </p>
                <Link className="btn btn-primary" to="/dashboard/collaboration">
                  Open Collaboration Hub
                </Link>
              </div>
            ) : (
              joinable.map((m) => (
                <article key={m.meeting_id} className={`meet-card status-${m.status}`}>
                  <div className="meet-card-top">
                    <strong>{m.topic}</strong>
                    <span className="pill ok">{m.status === "live" ? "live" : "in window"}</span>
                  </div>
                  <p className="muted">{m.scheduled_at_pkt ? `${m.scheduled_at_pkt} PKT` : "—"}</p>
                  <p className="muted mono">{m.livekit_room}</p>
                  <div className="meet-card-actions">
                    {m.status === "scheduled" ? (
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={busy || livekitReady === false}
                        onClick={() => void startMeeting(m.meeting_id)}
                      >
                        Call / Start live
                      </button>
                    ) : null}
                    {m.status === "live" ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-primary"
                          disabled={busy || livekitReady === false}
                          onClick={() => void enterMeeting(m.meeting_id)}
                        >
                          Join with Marcus
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() => void endMeeting(m.meeting_id)}
                        >
                          End
                        </button>
                      </>
                    ) : null}
                  </div>
                </article>
              ))
            )}
          </div>

          {upcoming.length > 0 ? (
            <div className="meet-list" style={{ marginTop: "1.5rem" }}>
              <h3>Upcoming scheduled</h3>
              {upcoming.map((m) => (
                <article key={m.meeting_id} className="meet-card">
                  <div className="meet-card-top">
                    <strong>{m.topic}</strong>
                    <span className="pill">{m.status}</span>
                  </div>
                  <p className="muted">{m.scheduled_at_pkt ? `${m.scheduled_at_pkt} PKT` : "—"}</p>
                  <p className="muted" style={{ fontSize: "0.82rem" }}>
                    Join unlocks near this time (±5 min), or start early with Call / Start live.
                  </p>
                </article>
              ))}
            </div>
          ) : null}

          <div className="meet-list" style={{ marginTop: "1.5rem" }}>
            <h3>Timed call budget sessions</h3>
            {timedSessions.length === 0 ? (
              <p className="muted">No timed sessions yet — scheduling a meeting reserves budget capacity.</p>
            ) : (
              timedSessions.slice(0, 8).map((s) => (
                <article key={s.session_id} className="meet-card">
                  <div className="meet-card-top">
                    <strong>{s.purpose || s.session_id}</strong>
                    <span className={`pill ${s.status === "active" ? "ok" : ""}`}>{s.status}</span>
                  </div>
                  <p className="muted" style={{ fontSize: "0.82rem" }}>
                    Cap {s.allowed_seconds ?? "—"}s · used {Math.round(Number(s.consumed_seconds || 0))}s
                    {s.created_at ? ` · ${s.created_at}` : ""}
                  </p>
                </article>
              ))
            )}
          </div>
        </div>
      ) : null}

      {showLiveControls ? (
        <section className="meet-live">
          <header className="meet-live-head">
            <div>
              <p className="calling-eyebrow">
                {spectatorMode || agentMeetId ? "Agent↔agent meeting" : "Live meeting"}
              </p>
              <h2 className="meet-title">
                {agentMeetProposal?.topic || activeMeeting?.topic || "Agent meeting"}
              </h2>
              <p className="muted">
                {activeMeeting?.livekit_room ? (
                  <>
                    Room <span className="mono">{activeMeeting.livekit_room}</span> · gate: {gate}
                  </>
                ) : (
                  <>Spectator · agents talk; you watch</>
                )}
              </p>
            </div>
            <div className="meet-live-actions">
              {activeMeeting && !spectatorMode && (gate === "closed" || gate === "user_waiting") ? (
                <>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy || livekitReady === false}
                    onClick={() => void enterMeeting(activeMeeting.meeting_id)}
                  >
                    Join with Marcus (speak)
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={busy || gate === "user_waiting"}
                    onClick={() => void requestJoin(activeMeeting.meeting_id)}
                  >
                    {gate === "user_waiting" ? "Waiting for agents…" : "Request to join"}
                  </button>
                </>
              ) : null}
              {activeMeeting && !spectatorMode && gate === "ready_prompt" ? (
                <>
                  <span className="meet-ready-q">Ready to join?</span>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => void confirmJoin(activeMeeting.meeting_id, true)}
                  >
                    Yes — enter with voice
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => void confirmJoin(activeMeeting.meeting_id, false)}
                  >
                    Not yet
                  </button>
                </>
              ) : null}
              {activeMeeting && !spectatorMode && gate === "admitted" && !tokenPayload ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  onClick={() => void enterMeeting(activeMeeting.meeting_id)}
                >
                  Join live call
                </button>
              ) : null}
              {activeMeeting ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={busy}
                  onClick={() => void endMeeting(activeMeeting.meeting_id)}
                >
                  End meeting
                </button>
              ) : null}
            </div>
          </header>

          <div className="meet-agent-strip">
            {agents.map((a) => (
              <div key={a.agent_type || a.name} className="meet-agent-chip">
                <AgentAvatar
                  name={a.name}
                  hue={a.avatar_hue ?? 210}
                  size={36}
                  presentation={a.avatar_presentation}
                  hair={a.avatar_hair}
                  skin={a.avatar_skin}
                  hairColor={a.avatar_hair_color}
                />
                <div>
                  <strong>{a.name}</strong>
                  <span className="muted">{a.role}</span>
                </div>
              </div>
            ))}
          </div>

          {tokenPayload ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr minmax(200px, 260px)", gap: "1rem" }}>
              <LiveKitMeetingRoom
                token={tokenPayload.token}
                url={tokenPayload.url}
                agents={agents}
                agentPresence={agentPresence}
                multiAgentPresence={multiAgentPresence}
                dialogue={dialogueTurns}
                spectatorMode={spectatorMode}
                onDisconnect={() => {
                  const sid = agentPresence?.timedSessionId;
                  if (sid && !spectatorMode) {
                    if (budgetActivatedRef.current) {
                      void api.callingTimedEnd(sid, "completed").catch(() => undefined);
                    } else {
                      void api.callingTimedCancelUncharged(sid).catch(() => undefined);
                    }
                  }
                  budgetActivatedRef.current = false;
                  setTokenPayload(null);
                  setAgentPresence(null);
                  setMultiAgentPresence(null);
                  setDialogueTurns(null);
                  autoConnectingRef.current = null;
                  agentMeetWatchRef.current = null;
                }}
                onError={(msg) => setError(msg)}
                onAgentJoined={(info) => {
                  if (info.timedSessionId && !spectatorMode) {
                    void api
                      .callingTimedActivate(info.timedSessionId)
                      .then(() => {
                        budgetActivatedRef.current = true;
                        return refresh();
                      })
                      .catch(() => undefined);
                  }
                }}
                onAgentJoinFailed={(info) => {
                  budgetActivatedRef.current = false;
                  if (info.timedSessionId && !spectatorMode) {
                    void api.callingTimedCancelUncharged(info.timedSessionId).catch(() => undefined);
                  }
                }}
              />
              {agentMeetId && spectatorMode ? (
                <aside className="meet-schedule" aria-label="Invite agent">
                  <h3>Mid-call</h3>
                  <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
                    Invite another agent — they join live and the call extends to 5 minutes.
                  </p>
                  <label className="meet-label">
                    Agent type
                    <input
                      className="field"
                      value={inviteAgentType}
                      onChange={(e) => setInviteAgentType(e.target.value)}
                      disabled={busy}
                      placeholder="marketing_manager"
                    />
                  </label>
                  <div className="meet-card-actions" style={{ marginTop: "0.5rem" }}>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busy}
                      onClick={() => void inviteAgentToCall()}
                    >
                      Invite &amp; extend
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      onClick={() => void extendAgentCall()}
                    >
                      Extend to 5 min
                    </button>
                  </div>
                </aside>
              ) : null}
            </div>
          ) : (
            <div className="meet-live-placeholder">
              <p>
                {gate === "closed"
                  ? "Marcus is ready on the other side. Join with Marcus to enter LiveKit and hear a spoken greeting."
                  : gate === "user_waiting"
                    ? "Agents: please wait while we finish discussion…"
                    : gate === "ready_prompt"
                      ? "Agents are ready. Confirm Yes to mint a LiveKit token and enter with voice."
                      : "Admitted — connecting camera, mic, and Marcus as a remote participant."}
              </p>
              <div className="meet-avatar-wall">
                {agents.map((a) => (
                  <div key={`wall-${a.agent_type || a.name}`} className="meet-wall-item">
                    <AgentAvatar
                      name={a.name}
                      hue={a.avatar_hue ?? 210}
                      size={64}
                      presentation={a.avatar_presentation}
                      hair={a.avatar_hair}
                      skin={a.avatar_skin}
                      hairColor={a.avatar_hair_color}
                    />
                    <span>{a.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {gate === "admitted" || tokenPayload ? (
            <div className="meet-work-chat">
              <h3>Meeting work chat</h3>
              <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
                Discuss logo, post copy, or layout with the specialist — live alongside LiveKit.
              </p>
              <div className="calling-chat meet-chat" role="log">
                {workChat.length === 0 ? (
                  <p className="muted waiting-copy">Try: “Change the Canva post logo” or “Update today’s caption”.</p>
                ) : (
                  workChat.map((m, i) => (
                    <div
                      key={m.message_id || `${i}-${m.body.slice(0, 12)}`}
                      className={`calling-bubble ${m.sender_name === "You" ? "user" : "agent"}`}
                    >
                      <p className="meet-bubble-meta">{m.sender_name || "Agent"}</p>
                      <p>{m.body}</p>
                    </div>
                  ))
                )}
              </div>
              <form className="calling-compose" onSubmit={(e) => void sendWorkChat(e)}>
                <input
                  className="field"
                  placeholder="Ask the agent to change content / logo…"
                  value={workInput}
                  onChange={(e) => setWorkInput(e.target.value)}
                  disabled={busy}
                  autoComplete="off"
                />
                <button className="btn btn-primary" type="submit" disabled={busy || !workInput.trim()}>
                  Send
                </button>
              </form>
            </div>
          ) : null}
        </section>
      ) : null}

      {view === "live" &&
      activeMeeting &&
      !activeJoinable &&
      !inviteAdmitted &&
      !agentMeetId ? (
        <div className="calling-idle">
          <p className="calling-eyebrow">Outside call window</p>
          <h2 className="calling-hero-title">Live controls hidden</h2>
          <p className="calling-lede muted">
            This meeting is not live and is outside the ±5 minute Asia/Karachi window.
          </p>
          <button type="button" className="btn btn-ghost" onClick={() => setView("lobby")}>
            Back to lobby
          </button>
        </div>
      ) : null}
    </AppShell>
  );
}
