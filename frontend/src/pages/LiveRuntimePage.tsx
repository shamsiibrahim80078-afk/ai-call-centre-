import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AppShell, { AgentAvatar, EmptyState, Metric } from "../components/AppShell";
import { api, subscribeJobEvents, subscribeWorkforceEvents, type JobEvent, type WorkforceSnapshot } from "../api/client";

const STAGE_ORDER = ["route", "perception", "evidence_rag", "verification", "reasoning", "finalize"];
/** Keep a "Just completed" strip after workers go idle so the page doesn't look dead mid-demo. */
const JUST_NOW_SEC = 120;

const PLATFORM_LANES = ["telegram", "threads", "x_twitter", "linkedin", "instagram"] as const;

const CHANNEL_LABELS: Record<string, string> = {
  telegram: "Telegram",
  x_twitter: "X",
  twitter: "X",
  linkedin: "LinkedIn",
  instagram: "Instagram",
  threads: "Threads",
  email: "Email",
  marketing_agency: "Marketing",
  canva: "Canva",
  browser_runtime: "Browser",
};

const STAGE_LABELS: Record<string, string> = {
  initializing: "Starting",
  task_execution: "Executing task",
  content_generation: "Generating content",
  draft_queue: "Queuing drafts for approval",
  result_collection: "Drafts ready for approval",
  connector_call: "Calling platform API",
  daily_pack_generation: "Building daily content pack",
  draft_queued: "Draft queued for approval",
  comms_send: "Platform send",
};

const AGENT_HUE: Record<string, number> = {
  marketing_manager: 210,
  content_creator: 195,
  social_poster: 225,
  telegram_community: 200,
  x_twitter_voice: 218,
  influencer_relations: 185,
};

type FeedKind = "working" | "just_now" | "draft" | "send" | "sdk" | "activity";

type LiveFeedItem = {
  id: string;
  kind: FeedKind;
  agent: string;
  channel: string;
  action: string;
  status: string;
  at?: string;
};

function pct(n: number | null | undefined): string {
  return n != null ? `${Math.round(Number(n) * 100)}%` : "—";
}

function normalizePlatform(raw: string | null | undefined): string {
  if (!raw) return "";
  const key = String(raw).replace(/^marketing_/, "").replace(/_comment$/, "").toLowerCase();
  if (key === "twitter") return "x_twitter";
  return key;
}

function channelLabel(raw: string | null | undefined): string {
  if (!raw) return "platform";
  const key = normalizePlatform(raw);
  return CHANNEL_LABELS[key] || key.replace(/_/g, " ");
}

function friendlyStage(stage: string | null | undefined): string {
  if (!stage) return "working";
  return STAGE_LABELS[stage] || String(stage).replace(/_/g, " ");
}

function ageSec(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 1000;
}

function relativeAge(iso: string | null | undefined): string {
  const age = ageSec(iso);
  if (age == null) return "";
  if (age < 8) return "just now";
  if (age < 60) return `${Math.round(age)}s ago`;
  if (age < 3600) return `${Math.round(age / 60)}m ago`;
  return `${Math.round(age / 3600)}h ago`;
}

function agentDisplay(agentType: string | null | undefined): string {
  if (!agentType) return "Agent";
  return String(agentType).replace(/_/g, " ");
}

function agentHue(agentType: string | null | undefined): number {
  if (!agentType) return 210;
  return AGENT_HUE[agentType] ?? 210;
}

function activityStatusLabel(ev: any): string {
  const stage = String(ev.workflow_stage || "");
  const apiStatus = String(ev.api_response_status || "");
  const completion = String(ev.completion_status || "");
  if (stage === "draft_queued" || apiStatus === "draft_only") return "draft queued";
  if (stage === "comms_send" && (apiStatus === "ok" || completion === "completed")) return "sent live";
  if (stage === "comms_send" && completion === "configuration_required") return "needs config";
  if (completion === "failed" || apiStatus === "error") return "failed";
  if (completion === "configuration_required") return "needs config";
  if (stage === "daily_pack_generation") return "pack queued";
  return completion || apiStatus || "activity";
}

function isLiveSend(ev: any): boolean {
  return (
    String(ev.workflow_stage || "") === "comms_send" &&
    (String(ev.api_response_status || "") === "ok" ||
      (String(ev.completion_status || "") === "completed" && String(ev.api_response_status || "") !== "draft_only"))
  );
}

function isDraftActivity(ev: any): boolean {
  const stage = String(ev.workflow_stage || "");
  const apiStatus = String(ev.api_response_status || "");
  return stage === "draft_queued" || apiStatus === "draft_only" || stage === "daily_pack_generation";
}

function humanAssignmentLine(a: any): string {
  const stage = friendlyStage(a.stage);
  const task = String(a.task || "").trim();
  if (task) return `${stage} — ${task}`;
  return stage;
}

function ProgressRing({ value, size = 52 }: { value: number; size?: number }) {
  const clamped = Math.max(0, Math.min(1, value || 0));
  const stroke = 3.5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - clamped);
  return (
    <svg className="lr-progress-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(79,140,255,0.15)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--electric-blue)"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="52%" textAnchor="middle" dominantBaseline="middle" className="lr-progress-text">
        {Math.round(clamped * 100)}%
      </text>
    </svg>
  );
}

function buildLiveFeed(opts: {
  assignments: any[];
  platformActivity: any[];
  pendingDrafts: any[];
  sdkTasks: any[];
  nowIdle: boolean;
}): LiveFeedItem[] {
  const items: LiveFeedItem[] = [];
  const seen = new Set<string>();

  for (const a of opts.assignments) {
    const id = `work-${a.worker_id || a.job_id || a.agent_type}`;
    if (seen.has(id)) continue;
    seen.add(id);
    items.push({
      id,
      kind: "working",
      agent: agentDisplay(a.agent_type),
      channel: channelLabel(a.platform || a.channel),
      action: humanAssignmentLine(a),
      status: "working now",
      at: a.started_at || a.updated_at,
    });
  }

  for (const t of opts.sdkTasks) {
    const id = `sdk-${t.task_id}`;
    if (seen.has(id)) continue;
    seen.add(id);
    items.push({
      id,
      kind: "sdk",
      agent: agentDisplay(t.to_agent || t.from_agent),
      channel: "SDK",
      action: `SDK task ${t.status}${t.from_agent ? ` from ${agentDisplay(t.from_agent)}` : ""}`,
      status: String(t.status || "running"),
      at: t.updated_at || t.created_at,
    });
  }

  for (const d of opts.pendingDrafts) {
    const id = `draft-${d.draft_id}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const ch = channelLabel(String(d.kind || "").replace(/^marketing_/, ""));
    items.push({
      id,
      kind: "draft",
      agent: agentDisplay(d.created_by_agent) || "Marketing",
      channel: ch,
      action: `${ch} draft awaiting approval: ${(d.body || d.subject || "").slice(0, 80)}${(d.body || "").length > 80 ? "…" : ""}`,
      status: "awaiting approval",
      at: d.created_at,
    });
  }

  for (const ev of opts.platformActivity) {
    const id = `act-${ev.id}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const age = ageSec(ev.finished_at || ev.started_at);
    const liveSend = isLiveSend(ev);
    const draftish = isDraftActivity(ev);
    let kind: FeedKind = "activity";
    if (liveSend) kind = "send";
    else if (draftish && opts.nowIdle && age != null && age <= JUST_NOW_SEC) kind = "just_now";
    else if (draftish) kind = "draft";
    else if (opts.nowIdle && age != null && age <= JUST_NOW_SEC) kind = "just_now";

    items.push({
      id,
      kind,
      agent: agentDisplay(ev.agent_type),
      channel: channelLabel(ev.platform),
      action: String(ev.task || ev.recent_activity || "Platform activity"),
      status: activityStatusLabel(ev),
      at: ev.finished_at || ev.started_at,
    });
  }

  const kindRank: Record<FeedKind, number> = {
    working: 0,
    sdk: 1,
    just_now: 2,
    send: 3,
    draft: 4,
    activity: 5,
  };
  items.sort((a, b) => {
    const kr = kindRank[a.kind] - kindRank[b.kind];
    if (kr !== 0) return kr;
    return (ageSec(a.at) ?? 9999) - (ageSec(b.at) ?? 9999);
  });
  return items.slice(0, 28);
}

export default function LiveRuntimePage() {
  const [params, setParams] = useSearchParams();
  const selectedJob = params.get("job") || "";

  const [jobs, setJobs] = useState<any[]>([]);
  const [workforce, setWorkforce] = useState<any>(null);
  const [platformActivity, setPlatformActivity] = useState<any[]>([]);
  const [marketingQueue, setMarketingQueue] = useState<any[]>([]);
  const [pendingDrafts, setPendingDrafts] = useState<any[]>([]);
  const [pendingDraftsCount, setPendingDraftsCount] = useState(0);
  const [sdkTasks, setSdkTasks] = useState<any[]>([]);
  const [collab, setCollab] = useState<any[]>([]);
  const [liveEvents, setLiveEvents] = useState<JobEvent[]>([]);
  const [, setSseStatus] = useState<"idle" | "connecting" | "live" | "closed" | "error">("idle");
  const [workforceSse, setWorkforceSse] = useState<"connecting" | "live" | "polling">("connecting");
  const [runtimeStatus, setRuntimeStatus] = useState<any>(null);
  const [visualProof, setVisualProof] = useState<any[]>([]);
  const [goLiveChecklist, setGoLiveChecklist] = useState<any>(null);
  const [browserUrl, setBrowserUrl] = useState("");
  const [browserResult, setBrowserResult] = useState<any>(null);
  const [browserBusy, setBrowserBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const stopRef = useRef<(() => void) | null>(null);

  const workforceSseRef = useRef(workforceSse);
  workforceSseRef.current = workforceSse;

  const refreshJobs = useCallback(async () => {
    try {
      const [j, wf, rs, q, act, proof, checklist] = await Promise.all([
        api.runtimeJobs(25),
        api.workforce(),
        api.runtimeStatus(),
        api.marketingQueue({ limit: 20, status: "draft_only" }).catch(() => ({ queue: [], count: 0 })),
        api.integrationsActivity({ limit: 60 }).catch(() => ({ items: [], activity: [] })),
        api.runtimeVisualProof(8).catch(() => ({ sessions: [] })),
        api.marketingGoLiveChecklist().catch(() => null),
      ]);
      setJobs(j.jobs || []);
      setWorkforce(wf);
      setRuntimeStatus(rs);
      const queue = q.queue || [];
      setMarketingQueue(queue);
      if (workforceSseRef.current !== "live") {
        setPendingDrafts(queue);
        setPendingDraftsCount(q.count ?? queue.length);
      }
      const actItems = act.items || act.activity || act.platform_activity || [];
      if (actItems.length) setPlatformActivity(actItems);
      setVisualProof(proof.sessions || []);
      if (checklist) setGoLiveChecklist(checklist);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load runtime jobs");
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
    const id = window.setInterval(() => void refreshJobs(), 2500);
    return () => window.clearInterval(id);
  }, [refreshJobs]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const stop = subscribeWorkforceEvents(
      (data: WorkforceSnapshot) => {
        if (cancelled) return;
        setWorkforceSse("live");
        const pool = data.roster?.workforce;
        if (pool) setWorkforce(pool);
        if (data.platform_activity) setPlatformActivity(data.platform_activity);
        if (typeof data.pending_drafts_count === "number") setPendingDraftsCount(data.pending_drafts_count);
        if (data.pending_drafts) setPendingDrafts(data.pending_drafts);
        if (data.sdk_tasks) setSdkTasks(data.sdk_tasks);
      },
      () => {
        if (!cancelled) setWorkforceSse("polling");
      }
    );
    return () => {
      cancelled = true;
      stop();
    };
  }, []);

  const liveAssignments = useMemo(() => workforce?.assignments || [], [workforce]);
  const marketingAssignments = useMemo(
    () =>
      liveAssignments.filter(
        (a: any) =>
          String(a.agent_type || "").includes("marketing") ||
          String(a.agent_type || "").includes("telegram") ||
          String(a.agent_type || "").includes("influencer") ||
          String(a.agent_type || "").includes("content") ||
          String(a.agent_type || "").includes("social") ||
          String(a.agent_type || "").includes("twitter")
      ),
    [liveAssignments]
  );

  const activeWorkers = workforce?.active_workers ?? liveAssignments.length;
  const nowIdle = activeWorkers === 0 && liveAssignments.length === 0;
  const isLiveWorking = liveAssignments.length > 0;

  const recentActivityFresh = useMemo(
    () =>
      platformActivity.filter((ev) => {
        const age = ageSec(ev.finished_at || ev.started_at);
        return age != null && age <= JUST_NOW_SEC;
      }),
    [platformActivity]
  );

  const liveFeed = useMemo(
    () =>
      buildLiveFeed({
        assignments: liveAssignments,
        platformActivity,
        pendingDrafts: pendingDrafts.length ? pendingDrafts : marketingQueue,
        sdkTasks,
        nowIdle,
      }),
    [liveAssignments, platformActivity, pendingDrafts, marketingQueue, sdkTasks, nowIdle]
  );

  const justCompleted = useMemo(() => {
    return liveFeed.filter((i) => {
      const age = ageSec(i.at);
      if (age == null || age > JUST_NOW_SEC) return false;
      if (i.kind === "working") return false;
      return i.kind === "just_now" || i.kind === "draft" || i.kind === "send" || i.kind === "activity";
    });
  }, [liveFeed]);

  const pendingCount =
    pendingDraftsCount || pendingDrafts.length || marketingQueue.filter((d) => d.external_action_status === "draft_only").length;
  const draftsForQueue = pendingDrafts.length ? pendingDrafts : marketingQueue;

  const platformLanes = useMemo(() => {
    return PLATFORM_LANES.map((lane) => {
      const working = liveAssignments.filter((a: any) => normalizePlatform(a.platform || a.channel) === lane);
      const drafts = draftsForQueue.filter((d: any) => normalizePlatform(String(d.kind || "").replace(/^marketing_/, "")) === lane);
      const activity = platformActivity.filter((ev) => {
        const p = normalizePlatform(ev.platform);
        if (p === lane) return true;
        if (p === "marketing_agency" && String(ev.recent_activity || "").toLowerCase().includes(lane.replace(/_/g, " ")))
          return true;
        if (p === "marketing_agency" && lane === "x_twitter" && String(ev.recent_activity || "").toLowerCase().includes("x"))
          return true;
        return false;
      });
      const latest = working[0]
        ? {
            kind: "working" as const,
            text: humanAssignmentLine(working[0]),
            agent: working[0].agent_type,
            at: working[0].started_at,
            status: "working",
          }
        : activity[0]
          ? {
              kind: isLiveSend(activity[0]) ? ("send" as const) : isDraftActivity(activity[0]) ? ("draft" as const) : ("activity" as const),
              text: String(activity[0].recent_activity || activity[0].task || "").slice(0, 120),
              agent: activity[0].agent_type,
              at: activity[0].finished_at || activity[0].started_at,
              status: activityStatusLabel(activity[0]),
            }
          : drafts[0]
            ? {
                kind: "draft" as const,
                text: String(drafts[0].body || drafts[0].subject || "Draft awaiting approval").slice(0, 120),
                agent: drafts[0].created_by_agent,
                at: drafts[0].created_at,
                status: "awaiting approval",
              }
            : null;
      return {
        key: lane,
        label: CHANNEL_LABELS[lane],
        workingCount: working.length,
        draftCount: drafts.length,
        latest,
      };
    });
  }, [liveAssignments, draftsForQueue, platformActivity]);

  const needsConfigPlatforms = useMemo(() => {
    const platforms = goLiveChecklist?.platforms || [];
    return platforms.filter(
      (p: any) =>
        ["threads", "instagram"].includes(String(p.platform || "")) &&
        p.send_ready === false
    );
  }, [goLiveChecklist]);

  const selectedIsLive = selectedJob.startsWith("agent-run-") || selectedJob.startsWith("team-");
  const selectedAssignment = useMemo(
    () => liveAssignments.find((a: any) => a.job_id === selectedJob) || null,
    [liveAssignments, selectedJob]
  );

  useEffect(() => {
    if (selectedJob) return;
    const preferred = marketingAssignments[0] || liveAssignments[0] || jobs[0];
    if (preferred) {
      setParams({ job: preferred.job_id || preferred.job_uuid }, { replace: true });
    }
  }, [selectedJob, marketingAssignments, liveAssignments, jobs, setParams]);

  useEffect(() => {
    stopRef.current?.();
    setLiveEvents([]);
    if (!selectedJob || selectedIsLive) return;
    setSseStatus("connecting");
    const stop = subscribeJobEvents(
      selectedJob,
      (ev) => {
        setSseStatus("live");
        setLiveEvents((prev) => [...prev.slice(-100), ev]);
      },
      () => setSseStatus("closed")
    );
    stopRef.current = stop;
    return () => stop();
  }, [selectedJob, selectedIsLive]);

  const refreshCollab = useCallback(async () => {
    if (!selectedJob || selectedIsLive) return;
    try {
      const data = await api.collaboration(selectedJob);
      setCollab(data.messages || data.collaboration || []);
    } catch {
      /* best-effort */
    }
  }, [selectedJob, selectedIsLive]);

  useEffect(() => {
    void refreshCollab();
    const id = window.setInterval(() => void refreshCollab(), 3000);
    return () => window.clearInterval(id);
  }, [refreshCollab]);

  const assignments = useMemo(
    () => (workforce?.assignments || []).filter((a: any) => a.job_id === selectedJob),
    [workforce, selectedJob]
  );

  const job = useMemo(() => jobs.find((j) => j.job_uuid === selectedJob) || null, [jobs, selectedJob]);

  const hitStages = useMemo(() => {
    const set = new Set<string>();
    for (const e of liveEvents) {
      if (e.stage) set.add(e.stage);
    }
    for (const c of collab) {
      if (c.stage) set.add(c.stage);
    }
    if (selectedAssignment?.stage) set.add(selectedAssignment.stage);
    return set;
  }, [liveEvents, collab, selectedAssignment]);

  async function captureBrowserSession() {
    if (!browserUrl.trim()) return;
    setBrowserBusy(true);
    setBrowserResult(null);
    try {
      const result = await api.runtimeBrowserSession(browserUrl.trim(), selectedJob || undefined);
      setBrowserResult(result);
      const proof = await api.runtimeVisualProof(8).catch(() => ({ sessions: [] }));
      setVisualProof(proof.sessions || []);
    } catch (e: any) {
      setBrowserResult({ status: "error", message: e.message || "Capture failed" });
    } finally {
      setBrowserBusy(false);
    }
  }

  return (
    <AppShell
      title="Live Agent Runtime"
      subtitle="Visual command board — drafts vs real sends, platform lanes, and live agent motion"
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span className={`live-indicator ${workforceSse === "live" ? "sse" : workforceSse === "polling" ? "polling" : ""}`}>
            <span className="live-dot" aria-hidden />
            Workforce {workforceSse === "live" ? "SSE" : workforceSse === "polling" ? "poll" : "…"}
          </span>
          <Link className="btn btn-ghost" to="/dashboard/marketing">
            Marketing
          </Link>
          <Link className="btn btn-ghost" to="/dashboard/workforce">
            Workforce
          </Link>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}

      <section className="metrics">
        <Metric label="Active now" value={String(activeWorkers)} tone={activeWorkers > 0 ? "ok" : undefined} />
        <Metric label="Marketing live" value={String(marketingAssignments.length)} />
        <Metric label="Pending approval" value={String(pendingCount)} tone={pendingCount > 0 ? "warn" : undefined} />
        <Metric label="Just completed" value={String(recentActivityFresh.length)} />
      </section>

      {/* —— Live now stage —— */}
      <section className={`lr-stage glass ${isLiveWorking ? "is-live" : nowIdle && justCompleted.length ? "is-afterglow" : ""}`}>
        <div className="lr-stage-head">
          <div className="lr-stage-title">
            <span className={`lr-live-badge ${isLiveWorking ? "on" : ""}`}>
              <span className="live-dot" aria-hidden />
              {isLiveWorking ? "Live now" : justCompleted.length ? "Just completed" : "Standing by"}
            </span>
            <h2>{isLiveWorking ? "Agents working" : justCompleted.length ? "Recent actions still visible" : "No agents active"}</h2>
            <p className="muted">
              {isLiveWorking
                ? "Animated stage reflects real pool assignments — drafts are queued, not posted."
                : "Run Marketing → team now, then watch tiles light up. Visibility holds ~18s after fast runs."}
            </p>
          </div>
          {isLiveWorking ? <div className="lr-stage-scan" aria-hidden /> : null}
        </div>

        {liveAssignments.length === 0 ? (
          <div className="lr-stage-empty">
            <EmptyState
              title="Waiting for a run"
              body="Open Marketing Agency → Run marketing team now, then return here to watch agents draft per platform."
              action={
                <Link className="btn btn-primary" to="/dashboard/marketing">
                  Go to Marketing
                </Link>
              }
            />
          </div>
        ) : (
          <div className="lr-agent-grid">
            {liveAssignments.map((a: any) => (
              <button
                key={a.worker_id || a.job_id}
                type="button"
                className={`lr-agent-tile ${a.job_id === selectedJob ? "active" : ""} ${a.finished ? "finishing" : "working"}`}
                onClick={() => setParams({ job: a.job_id })}
              >
                <div className="lr-agent-tile-top">
                  <div className="lr-agent-avatar-wrap">
                    <AgentAvatar name={agentDisplay(a.agent_type)} hue={agentHue(a.agent_type)} size={44} />
                    <span className="lr-working-pulse" aria-hidden />
                  </div>
                  <ProgressRing value={Number(a.progress) || 0} />
                </div>
                <strong className="lr-agent-name">{agentDisplay(a.agent_type)}</strong>
                <span className="lr-agent-channel">{channelLabel(a.platform || a.channel)}</span>
                <p className="lr-agent-task">{humanAssignmentLine(a)}</p>
                <div className="lr-agent-meta">
                  <span className="pill ok">{friendlyStage(a.stage)}</span>
                  <time className="muted">{a.elapsed_sec != null ? `${Math.round(a.elapsed_sec)}s` : relativeAge(a.started_at)}</time>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* —— Platform lanes —— */}
      <section className="lr-lanes" aria-label="Platform lanes">
        {platformLanes.map((lane) => (
          <article key={lane.key} className={`lr-lane glass ${lane.workingCount ? "is-active" : ""}`}>
            <header className="lr-lane-head">
              <strong>{lane.label}</strong>
              {lane.workingCount ? <span className="pill ok">live</span> : lane.draftCount ? <span className="pill">draft</span> : <span className="muted">idle</span>}
            </header>
            {lane.latest ? (
              <div className={`lr-lane-body kind-${lane.latest.kind}`}>
                <p>{lane.latest.text || "—"}</p>
                <div className="lr-lane-meta">
                  <span className="muted">{agentDisplay(lane.latest.agent)}</span>
                  <span className={`pill ${lane.latest.kind === "send" ? "ok" : ""}`}>{lane.latest.status}</span>
                  <time className="muted">{relativeAge(lane.latest.at)}</time>
                </div>
              </div>
            ) : (
              <p className="muted lr-lane-empty">No activity yet</p>
            )}
          </article>
        ))}
      </section>

      {needsConfigPlatforms.length > 0 ? (
        <div className="banner lr-config-cta">
          <span>
            Threads / Instagram real send needs Meta tokens in env — drafts still queue without them.
            {needsConfigPlatforms.map((p: any) => ` ${channelLabel(p.platform)} missing: ${(p.env_vars || []).join(", ") || "credentials"}.`).join("")}
          </span>
          <Link className="btn btn-ghost" to="/dashboard/integrations">
            Configure integrations
          </Link>
        </div>
      ) : null}

      {pendingCount > 0 ? (
        <section className="lr-approve-panel glass">
          <div className="lr-approve-head">
            <div>
              <h2>Pending approval</h2>
              <p className="muted" style={{ margin: 0 }}>
                {pendingCount} draft{pendingCount === 1 ? "" : "s"} — nothing posts until you approve on Marketing.
              </p>
            </div>
            <Link className="btn btn-primary" to="/dashboard/marketing">
              Approve on Marketing
            </Link>
          </div>
          <ul className="lr-approve-list">
            {draftsForQueue.slice(0, 6).map((d: any) => (
              <li key={d.draft_id}>
                <span className="pill">{channelLabel(String(d.kind || "").replace(/^marketing_/, ""))}</span>
                <span className="lr-approve-body">{(d.body || d.subject || "").slice(0, 100)}{(d.body || "").length > 100 ? "…" : ""}</span>
                <span className="pill">draft only</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {justCompleted.length > 0 ? (
        <section className="just-now-strip glass lr-just-completed" aria-live="polite">
          <div className="just-now-strip-head">
            <span className="live-dot" aria-hidden />
            <strong>Just completed</strong>
            <span className="muted">Last {JUST_NOW_SEC}s — drafts/queues stay visible after workers idle</span>
          </div>
          <ul className="lr-action-strip">
            {justCompleted.slice(0, 8).map((item) => (
              <li key={`jc-${item.id}`} className={`lr-action-chip kind-${item.kind}`}>
                <span className="pill ok">{item.channel}</span>
                <span>
                  <strong>{item.agent}</strong> {item.action.slice(0, 90)}
                  {item.action.length > 90 ? "…" : ""}
                </span>
                <time className="muted">{relativeAge(item.at)}</time>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {visualProof.length > 0 ? (
        <section className="lr-visual-proof glass">
          <div className="lr-approve-head">
            <div>
              <h2>Visual proof</h2>
              <p className="muted" style={{ margin: 0 }}>
                Real Playwright screenshots from browser captures you requested — not fabricated post previews.
              </p>
            </div>
          </div>
          <div className="lr-proof-strip">
            {visualProof.map((s: any) => (
              <figure key={s.session_id} className="lr-proof-tile">
                <img src={api.runtimeBrowserSessionImageUrl(s.session_id)} alt="Browser session capture" />
                <figcaption className="muted">{relativeAge(s.captured_at) || "capture"}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      ) : null}

      <div className="workspace-layout lr-lower">
        <aside className="workspace-rail glass">
          <h3 className="subh" style={{ marginTop: 0 }}>
            Live assignments
          </h3>
          <ul className="workspace-agent-list">
            {liveAssignments.length === 0 ? (
              <li className="muted workspace-agent-empty">
                {justCompleted.length ? "Idle — see Just completed above." : "No agents working."}
              </li>
            ) : (
              liveAssignments.map((a: any) => (
                <li key={a.worker_id || a.job_id}>
                  <button
                    type="button"
                    className={`workspace-agent-row ${a.job_id === selectedJob ? "active" : ""}`}
                    onClick={() => setParams({ job: a.job_id })}
                  >
                    <div className="workspace-agent-row-text">
                      <strong>{agentDisplay(a.agent_type)}</strong>
                      <span className="muted">{humanAssignmentLine(a).slice(0, 64)}</span>
                    </div>
                    <span className="pill ok">{channelLabel(a.platform || a.channel)}</span>
                  </button>
                </li>
              ))
            )}
          </ul>

          <h3 className="subh">Persisted jobs</h3>
          <ul className="workspace-agent-list">
            {jobs.length === 0 ? (
              <li className="muted workspace-agent-empty">No persisted jobs yet.</li>
            ) : (
              jobs.map((j) => (
                <li key={j.job_uuid}>
                  <button
                    type="button"
                    className={`workspace-agent-row ${j.job_uuid === selectedJob ? "active" : ""}`}
                    onClick={() => setParams({ job: j.job_uuid })}
                  >
                    <div className="workspace-agent-row-text">
                      <strong>{j.title || j.job_uuid.slice(0, 8)}</strong>
                      <span className="muted mono">{j.mode || "job"}</span>
                    </div>
                    <span className={`pill ${j.status === "completed" || j.status === "processing" ? "ok" : ""}`}>{j.status}</span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </aside>

        <section className="workspace-main">
          <section className="panel glass live-platform-feed-panel">
            <h2>Live action strip</h2>
            <p className="muted" style={{ marginTop: 0 }}>
              Merges active workers, platform activity, pending drafts, and SDK tasks. Labels stay honest: draft ≠ sent live.
            </p>
            {liveFeed.length === 0 ? (
              <p className="muted waiting-copy">No platform activity yet — run marketing agents to populate this feed.</p>
            ) : (
              <ul className="live-platform-feed">
                {liveFeed.map((item) => (
                  <li key={item.id} className={`live-feed-item kind-${item.kind}`}>
                    <div className="live-feed-meta">
                      <span
                        className={`pill ${
                          item.kind === "working" || item.kind === "send" || item.kind === "just_now" ? "ok" : ""
                        }`}
                      >
                        {item.kind === "working"
                          ? "working"
                          : item.kind === "just_now"
                            ? "just now"
                            : item.kind === "send"
                              ? "sent live"
                              : item.kind === "draft"
                                ? "draft"
                                : item.kind === "sdk"
                                  ? "sdk"
                                  : item.status}
                      </span>
                      <span className="mono">{item.channel}</span>
                      <time className="muted">{relativeAge(item.at)}</time>
                    </div>
                    <div className="live-feed-body">
                      <strong>{item.agent}</strong>
                      <span>{item.action}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel glass">
            <h2>Platform activity log</h2>
            {platformActivity.length === 0 ? (
              <p className="muted waiting-copy">No recorded connector/draft events yet.</p>
            ) : (
              <ul className="sse-log">
                {platformActivity.slice(0, 20).map((ev: any) => (
                  <li key={ev.id}>
                    <span className="mono">{channelLabel(ev.platform)}</span>
                    <span
                      className={`pill ${
                        isLiveSend(ev) ? "ok" : ev.completion_status === "failed" ? "bad" : ""
                      }`}
                    >
                      {activityStatusLabel(ev)}
                    </span>
                    <span>{ev.task || ev.recent_activity}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {selectedIsLive && selectedAssignment ? (
            <section className="panel glass workflow-panel">
              <h2>
                {agentDisplay(selectedAssignment.agent_type)} — {friendlyStage(selectedAssignment.stage)}
              </h2>
              <p className="muted">{humanAssignmentLine(selectedAssignment)}</p>
              <ul className="stat-list">
                <li>
                  <span>Progress</span>
                  <strong>{pct(selectedAssignment.progress)}</strong>
                </li>
                <li>
                  <span>Channel</span>
                  <strong>{channelLabel(selectedAssignment.platform || selectedAssignment.channel)}</strong>
                </li>
                <li>
                  <span>Elapsed</span>
                  <strong>{selectedAssignment.elapsed_sec ?? "—"}s</strong>
                </li>
              </ul>
            </section>
          ) : !job && !selectedJob ? (
            <div className="panel glass">
              <EmptyState
                title="Nothing selected"
                body="Run the marketing team or pick a live assignment from the stage."
              />
            </div>
          ) : !selectedIsLive && job ? (
            <>
              <section className="panel glass workflow-panel">
                <h2>LangGraph execution — {job?.title || selectedJob.slice(0, 8)}</h2>
                <div className="workflow-nodes">
                  {STAGE_ORDER.map((node) => {
                    const hit =
                      hitStages.has(node) ||
                      Array.from(hitStages).some((s) => s.includes(node)) ||
                      (node === "finalize" && hitStages.has("completed"));
                    return (
                      <div key={node} className={`wf-node ${hit ? "is-on" : ""}`}>
                        {node}
                      </div>
                    );
                  })}
                </div>
                {assignments.length === 0 ? (
                  <p className="muted" style={{ marginTop: "0.75rem" }}>
                    No agents currently assigned to this job.
                  </p>
                ) : (
                  <ul className="assignment-list" style={{ marginTop: "0.85rem" }}>
                    {assignments.map((a: any) => (
                      <li key={a.worker_id}>
                        <span className="mono">{a.agent_type}</span>
                        <span>{humanAssignmentLine(a)}</span>
                        <span className="mono">{pct(a.progress)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <div className="two-col">
                <section className="panel glass">
                  <h2>Live event stream</h2>
                  {liveEvents.length === 0 ? (
                    <p className="muted waiting-copy">No SSE events yet for this job.</p>
                  ) : (
                    <ul className="sse-log">
                      {liveEvents
                        .slice(-30)
                        .reverse()
                        .map((ev, i) => (
                          <li key={`${ev.stage}-${i}`}>
                            <span className="mono">{ev.stage}</span>
                            <span>{ev.message || ev.agent_type || ""}</span>
                          </li>
                        ))}
                    </ul>
                  )}
                </section>
                <section className="panel glass">
                  <h2>Collaboration trace</h2>
                  {collab.length === 0 ? (
                    <p className="muted waiting-copy">No collaboration events yet.</p>
                  ) : (
                    <ul className="collab-feed">
                      {collab.slice(0, 20).map((m: any) => (
                        <li key={m.id} className="collab-feed-item">
                          <div>
                            <p style={{ margin: 0 }}>
                              <strong>{m.speaker?.name || m.agent_type || "Agent"}</strong>: {m.message}
                            </p>
                            <time>{m.timestamp}</time>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            </>
          ) : null}

          <section className="panel glass">
            <h2>Browser session recorder (optional)</h2>
            {!runtimeStatus?.enabled ? (
              <p className="muted">
                {runtimeStatus?.message ||
                  "Disabled — set VERIDIQ_BROWSER_RUNTIME=1 to enable. Live feed works without it."}
              </p>
            ) : runtimeStatus.status !== "ready" ? (
              <p className="muted">{runtimeStatus.message}</p>
            ) : (
              <>
                <p className="muted">Capture a screenshot of a public URL you provide — shown in Visual proof above.</p>
                <div className="verify-form" style={{ flexDirection: "row", gap: "0.5rem" }}>
                  <input
                    className="field"
                    placeholder="https://example.com"
                    value={browserUrl}
                    onChange={(e) => setBrowserUrl(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={browserBusy || !browserUrl.trim()}
                    onClick={() => void captureBrowserSession()}
                  >
                    {browserBusy ? "Capturing…" : "Capture session"}
                  </button>
                </div>
                {browserResult ? (
                  browserResult.status === "ok" ? (
                    <p className="muted" style={{ marginTop: "0.75rem" }}>
                      Captured: {browserResult.page_title}
                    </p>
                  ) : (
                    <p className="banner error" style={{ marginTop: "0.75rem" }}>
                      {browserResult.message}
                    </p>
                  )
                ) : null}
              </>
            )}
          </section>
        </section>
      </div>
    </AppShell>
  );
}
