import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AppShell, { AgentAvatar, EmptyState, Metric } from "../components/AppShell";
import { api, subscribeWorkforceEvents, type WorkforceSnapshot } from "../api/client";

type LiveMode = "connecting" | "sse" | "polling";

const CAMPAIGN_CHANNELS = ["telegram", "x_twitter", "linkedin", "instagram", "threads"];
const COMMENT_CHANNELS = ["x_twitter", "linkedin", "instagram", "telegram", "threads"];
const MARKETING_AGENT_TYPES = [
  "marketing_manager",
  "content_creator",
  "social_poster",
  "telegram_community",
  "x_twitter_voice",
  "influencer_relations",
];

function draftStatusTone(status: string): string {
  if (status === "sent" || status === "completed") return "ok";
  if (status?.includes("failed") || status === "rejected_by_user") return "bad";
  if (status === "configuration_required" || status === "approved_pending_integration") return "warn";
  return "";
}

function channelFromKind(kind: string): string {
  return kind.replace(/^marketing_/, "");
}

/** Start/Run now/Pause/Resume/Stop for one marketing agent — identical
 * control surface to the Agent Workspace so the two pages behave the same
 * way. "Run now" hits the real backend immediately: with no campaign_id
 * supplied, the agent auto-targets the always-on default campaign, so
 * there is nothing to fill in first. */
function AgentControls({
  agentType,
  controlStatus,
  onChanged,
}: {
  agentType: string;
  controlStatus?: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const status = controlStatus || "running";

  async function run(action: "start" | "stop" | "pause" | "resume") {
    setBusy(action);
    try {
      if (action === "start") await api.agentControlStart(agentType);
      if (action === "stop") await api.agentControlStop(agentType);
      if (action === "pause") await api.agentControlPause(agentType);
      if (action === "resume") await api.agentControlResume(agentType);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function runNow() {
    setBusy("run");
    setNote(null);
    try {
      const result = await api.runAgent(agentType, {});
      setNote(result.status === "started" ? "Working now — drafts will land in the queue below." : String(result.detail || "Started."));
      onChanged();
    } catch (e: any) {
      setNote(e.message || "Run failed to start");
    } finally {
      setBusy(null);
      window.setTimeout(() => setNote(null), 6000);
    }
  }

  return (
    <div style={{ marginTop: "0.6rem" }}>
      <div className="control-actions">
        <button className="btn btn-primary btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => void run("start")}>
          Start
        </button>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          disabled={busy !== null || status !== "running"}
          onClick={() => void runNow()}
          title="Execute this agent right now — auto-targets the default campaign"
        >
          {busy === "run" ? "Running…" : "Run now"}
        </button>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "paused"} onClick={() => void run("pause")}>
          Pause
        </button>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => void run("resume")}>
          Resume
        </button>
        <button className="btn btn-danger btn-sm" type="button" disabled={busy !== null || status === "stopped"} onClick={() => void run("stop")}>
          Stop
        </button>
      </div>
      {note ? (
        <p className="muted" style={{ marginTop: "0.35rem", fontSize: "0.82rem" }}>
          {note}
        </p>
      ) : null}
    </div>
  );
}

export default function MarketingAgencyPage() {
  const [cards, setCards] = useState<any[]>([]);
  const [workforce, setWorkforce] = useState<any>(null);
  const [liveMode, setLiveMode] = useState<LiveMode>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [teamBusy, setTeamBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [campaign, setCampaign] = useState<any>(null);
  const [queue, setQueue] = useState<any[]>([]);
  const [queueBusy, setQueueBusy] = useState(false);

  const [showAdvanced, setShowAdvanced] = useState(false);

  // --- Advanced (secondary) campaign manager — collapsed by default -------
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [advSelectedId, setAdvSelectedId] = useState<string | null>(null);
  const [advDetail, setAdvDetail] = useState<any>(null);
  const [advQueue, setAdvQueue] = useState<any[]>([]);
  const [features, setFeatures] = useState<any>(null);
  const [advBusy, setAdvBusy] = useState(false);

  const [name, setName] = useState("VeriDiQ Launch Push");
  const [brief, setBrief] = useState(
    "VeriDiQ is an AI-native truth verification and workforce platform — verify claims, run a live AI team, and optionally attest findings on-chain."
  );
  const [channels, setChannels] = useState<string[]>(CAMPAIGN_CHANNELS);

  const [commentChannel, setCommentChannel] = useState("x_twitter");
  const [commentTarget, setCommentTarget] = useState("");
  const [commentText, setCommentText] = useState("Great point — VeriDiQ's truth verification is built for exactly this.");
  const [commentDraft, setCommentDraft] = useState<any>(null);

  const [canvaTitle, setCanvaTitle] = useState("VeriDiQ Feature Spotlight");
  const [canvaResult, setCanvaResult] = useState<any>(null);
  const [goLive, setGoLive] = useState<any>(null);
  const [lastApproveResult, setLastApproveResult] = useState<any>(null);
  const [influencerQuery, setInfluencerQuery] = useState("AI truth verification creators");
  const [influencerNiche, setInfluencerNiche] = useState("Web3 / AI agents");
  const [influencerBusy, setInfluencerBusy] = useState(false);
  const [influencerResearch, setInfluencerResearch] = useState<any>(null);

  const [storyFeature, setStoryFeature] = useState("truth_verification");
  const [storyDuration, setStoryDuration] = useState(30);
  const [storyboard, setStoryboard] = useState<any>(null);
  const [renderResult, setRenderResult] = useState<any>(null);

  // --- Primary: identity-first team roster + live pool -------------------

  const refreshTeam = useCallback(async () => {
    try {
      const team = await api.marketingTeam();
      setCards(team.cards || []);
      setWorkforce(team.workforce || null);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load marketing team");
    }
  }, []);

  useEffect(() => {
    void refreshTeam();
    const id = window.setInterval(() => void refreshTeam(), 4000);
    return () => window.clearInterval(id);
  }, [refreshTeam]);

  useEffect(() => {
    void api
      .marketingGoLiveChecklist()
      .then(setGoLive)
      .catch((e: any) =>
        setGoLive({
          ready_count: 0,
          total: 0,
          all_ready: false,
          platforms: [],
          error: true,
          note: e?.message || "Could not load checklist — restart backend on port 8001, then hard-refresh.",
        })
      );
  }, []);

  // Live overlay: merge fast SSE status updates into the polled roster, same
  // pattern as the Agent Workspace, so this page is observably "live" too.
  useEffect(() => {
    let cancelled = false;
    const stopSse = subscribeWorkforceEvents(
      (data: WorkforceSnapshot) => {
        if (cancelled) return;
        setLiveMode("sse");
        const pool = data.roster?.workforce || data.active_assignments;
        if (data.roster?.workforce) {
          setWorkforce(data.roster.workforce);
        } else if (data.active_assignments) {
          setWorkforce((prev: any) => ({
            ...(prev || {}),
            assignments: data.active_assignments,
            active_workers: data.active_assignments.length,
          }));
        }
        const marketingTypes = new Set(MARKETING_AGENT_TYPES);
        const liveCards = (data.cards || []).filter((c: any) => marketingTypes.has(c.agent_type));
        if (liveCards.length > 0) {
          setCards((prev) => {
            const byType = new Map(liveCards.map((c: any) => [c.agent_type, c]));
            return prev.map((a) => {
              const live = byType.get(a.agent_type);
              return live
                ? {
                    ...a,
                    status: live.status,
                    status_label: live.status_label,
                    current_task: live.current_task,
                    progress: live.progress,
                    workflow_stage: live.workflow_stage,
                  }
                : a;
            });
          });
        }
        if (pool && typeof pool === "object" && "active_workers" in pool) {
          setWorkforce(pool);
        }
        if (pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      },
      () => {
        if (cancelled) return;
        setLiveMode("polling");
        if (!pollRef.current) {
          pollRef.current = window.setInterval(() => void refreshTeam(), 3000);
        }
      }
    );
    return () => {
      cancelled = true;
      stopSse();
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [refreshTeam]);

  // Default campaign — created silently on first load if it doesn't exist
  // yet, so the primary view never shows a campaign-create form.
  useEffect(() => {
    void api
      .marketingDefaultCampaign()
      .then((c) => setCampaignId(c.campaign_id))
      .catch((e) => setError(e.message || "Failed to load default campaign"));
  }, []);

  const refreshCampaignQueue = useCallback(async (id: string) => {
    try {
      const [d, q] = await Promise.all([api.marketingCampaignDetail(id), api.marketingQueue({ campaignId: id, limit: 100 })]);
      setCampaign(d);
      setQueue(q.queue || []);
    } catch (e: any) {
      setError(e.message || "Failed to load content queue");
    }
  }, []);

  useEffect(() => {
    if (!campaignId) return;
    void refreshCampaignQueue(campaignId);
    const id = window.setInterval(() => void refreshCampaignQueue(campaignId), 5000);
    return () => window.clearInterval(id);
  }, [campaignId, refreshCampaignQueue]);

  async function runTeamNow() {
    setTeamBusy(true);
    setError(null);
    try {
      const result = await api.marketingRunNow();
      setNotice(result.message);
      // Burst-poll so Working > 0 is visible immediately after the click.
      for (let i = 0; i < 8; i++) {
        await refreshTeam();
        await new Promise((r) => window.setTimeout(r, 400));
      }
      if (campaignId) await refreshCampaignQueue(campaignId);
    } catch (e: any) {
      setError(e.message || "Failed to run the marketing team");
    } finally {
      setTeamBusy(false);
    }
  }

  async function onApproveQueueItem(item: any, approved: boolean) {
    setQueueBusy(true);
    setError(null);
    setLastApproveResult(null);
    try {
      const result = await api.commsApprove(item.draft_id, approved, channelFromKind(item.kind));
      setLastApproveResult(result);
      if (campaignId) await refreshCampaignQueue(campaignId);
    } catch (err: any) {
      setError(err.message || "Approval failed");
    } finally {
      setQueueBusy(false);
    }
  }

  async function onApproveAllPending() {
    const pending = queue.filter((q) => q.external_action_status === "draft_only");
    if (pending.length === 0) return;
    setQueueBusy(true);
    setError(null);
    setLastApproveResult(null);
    try {
      const result = await api.commsApproveBatch(
        pending.map((item) => ({ draft_id: item.draft_id, channel: channelFromKind(item.kind) })),
        true,
        // Cadence only after live sends; default off in UI so Approve-all never blocks for minutes.
        false
      );
      const last = result.results?.[result.results.length - 1];
      if (last) setLastApproveResult(last);
      setNotice(
        result.message ||
          `Approved ${pending.length} draft(s)${result.total_wait_sec ? ` (${result.total_wait_sec}s cadence spacing)` : ""}. Missing platform keys return configuration_required — drafts stay queued honestly.`
      );
      if (campaignId) await refreshCampaignQueue(campaignId);
    } catch (err: any) {
      setError(err.message || "Batch approval failed");
    } finally {
      setQueueBusy(false);
    }
  }

  // --- Advanced (secondary) campaign manager actions ----------------------

  const refreshCampaigns = useCallback(async () => {
    try {
      const c = await api.marketingCampaigns();
      setCampaigns(c.campaigns || []);
    } catch (e: any) {
      setError(e.message || "Failed to load campaigns");
    }
  }, []);

  const refreshAdvDetail = useCallback(async (id: string) => {
    try {
      const [d, q] = await Promise.all([api.marketingCampaignDetail(id), api.marketingQueue({ campaignId: id, limit: 100 })]);
      setAdvDetail(d);
      setAdvQueue(q.queue || []);
    } catch (e: any) {
      setError(e.message || "Failed to load campaign detail");
    }
  }, []);

  useEffect(() => {
    if (!showAdvanced) return;
    void refreshCampaigns();
    void api.marketingFeatures().then(setFeatures).catch(() => undefined);
    const id = window.setInterval(() => void refreshCampaigns(), 6000);
    return () => window.clearInterval(id);
  }, [showAdvanced, refreshCampaigns]);

  useEffect(() => {
    if (!advSelectedId) return;
    void refreshAdvDetail(advSelectedId);
    const id = window.setInterval(() => void refreshAdvDetail(advSelectedId), 5000);
    return () => window.clearInterval(id);
  }, [advSelectedId, refreshAdvDetail]);

  function toggleChannel(c: string) {
    setChannels((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  }

  async function onCreateCampaign(e: FormEvent) {
    e.preventDefault();
    setAdvBusy(true);
    setError(null);
    try {
      const c = await api.marketingCampaignCreate({ name, product_brief: brief, channels });
      setAdvSelectedId(c.campaign_id);
      await refreshCampaigns();
      setNotice(`Campaign "${c.name}" created.`);
    } catch (err: any) {
      setError(err.message || "Failed to create campaign");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onRunDaily() {
    if (!advSelectedId) return;
    setAdvBusy(true);
    setError(null);
    try {
      const result = await api.marketingDailyRun(advSelectedId);
      setNotice(result.message || `Queued ${result.count} draft(s).`);
      await refreshAdvDetail(advSelectedId);
    } catch (err: any) {
      setError(err.message || "Failed to generate daily pack");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onSetStatus(status: string) {
    if (!advSelectedId) return;
    setAdvBusy(true);
    try {
      await api.marketingCampaignStatus(advSelectedId, status);
      await refreshAdvDetail(advSelectedId);
      await refreshCampaigns();
    } catch (err: any) {
      setError(err.message || "Failed to update campaign status");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onApproveAdvQueueItem(item: any, approved: boolean) {
    setAdvBusy(true);
    setError(null);
    try {
      await api.commsApprove(item.draft_id, approved, channelFromKind(item.kind));
      if (advSelectedId) await refreshAdvDetail(advSelectedId);
    } catch (err: any) {
      setError(err.message || "Approval failed");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onGenerateComment() {
    setAdvBusy(true);
    setError(null);
    try {
      const preview = await api.marketingCommentPreview({
        channel: commentChannel,
        agent_type: "influencer_relations",
        feature: storyFeature,
      });
      setCommentText(preview.text || "");
      setNotice("Adrian reply generated — edit if needed, then Draft comment.");
    } catch (err: any) {
      setError(err.message || "Failed to generate comment");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onInfluencerResearch(e: FormEvent) {
    e.preventDefault();
    setInfluencerBusy(true);
    setError(null);
    try {
      const result = await api.influencerResearch({
        query: influencerQuery,
        niche: influencerNiche || undefined,
        max_results: 8,
        summarize: true,
      });
      setInfluencerResearch(result);
      if (result.status === "configuration_required") {
        setNotice(result.message || "Configure Tavily / Exa / SerpAPI for creator research.");
      }
    } catch (err: any) {
      setError(err.message || "Influencer research failed");
    } finally {
      setInfluencerBusy(false);
    }
  }

  async function onDraftComment(e: FormEvent) {
    e.preventDefault();
    setAdvBusy(true);
    setError(null);
    try {
      const result = await api.marketingComment({
        channel: commentChannel,
        text: commentText,
        target_ref: commentTarget,
        campaign_id: advSelectedId || campaignId || undefined,
      });
      setCommentDraft(result.draft);
    } catch (err: any) {
      setError(err.message || "Failed to draft comment");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onApproveComment(approved: boolean) {
    if (!commentDraft?.draft_id) return;
    setAdvBusy(true);
    try {
      const result = await api.commsApprove(commentDraft.draft_id, approved, `${commentChannel}_comment`);
      setCommentDraft(result.draft || commentDraft);
      setNotice(result.message || result.status);
    } catch (err: any) {
      setError(err.message || "Approval failed");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onCreateDesign(e: FormEvent) {
    e.preventDefault();
    setAdvBusy(true);
    setError(null);
    try {
      setCanvaResult(await api.marketingCanvaDesign({ title: canvaTitle }));
    } catch (err: any) {
      setError(err.message || "Canva design failed");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onCreateStoryboard(e: FormEvent) {
    e.preventDefault();
    setAdvBusy(true);
    setError(null);
    setRenderResult(null);
    try {
      setStoryboard(
        await api.marketingStoryboardCreate({
          campaign_id: advSelectedId || campaignId || undefined,
          feature: storyFeature,
          duration_sec: storyDuration,
        })
      );
    } catch (err: any) {
      setError(err.message || "Storyboard generation failed");
    } finally {
      setAdvBusy(false);
    }
  }

  async function onRenderVideo() {
    if (!storyboard?.storyboard_id) return;
    setAdvBusy(true);
    try {
      setRenderResult(await api.marketingVideoRender(storyboard.storyboard_id));
    } catch (err: any) {
      setError(err.message || "Render request failed");
    } finally {
      setAdvBusy(false);
    }
  }

  const activeWorkers =
    workforce?.active_workers ?? cards.filter((c) => c.status === "working").length;
  const idleWorkers = workforce?.idle_workers ?? Math.max(0, cards.length - activeWorkers);
  const dailyStatus = campaign?.today_queue;
  const pendingCount = queue.filter((q) => q.external_action_status === "draft_only").length;

  return (
    <AppShell
      title="Marketing Agency"
      subtitle="Renata, Jasper, Lena, Theo, Nova & Adrian — your marketing team drafts for Telegram, X, LinkedIn, and Instagram"
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
          <span className={`live-indicator ${liveMode === "connecting" ? "" : liveMode}`}>
            <span className="live-dot" aria-hidden />
            {liveMode === "sse" ? "Live · SSE" : liveMode === "polling" ? "Live · Polling" : "Connecting…"}
          </span>
          <button className="btn btn-primary" type="button" disabled={teamBusy} onClick={() => void runTeamNow()}>
            {teamBusy ? "Starting team…" : "Run marketing team now"}
          </button>
          <Link className="btn btn-ghost" to="/dashboard/live">
            Watch live
          </Link>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <div className="banner" style={{ marginBottom: "1rem" }}>
        <strong>Feature-complete offline.</strong> Run marketing team, per-agent Run now, content queue, and paced approve
        all work without platform keys. Approve attempts real sends — missing credentials return{" "}
        <code>configuration_required</code>, never fake posts. Paste API tokens into <code>.env</code> when ready (
        <Link className="linkish" to="/dashboard/integrations">
          Integrations
        </Link>
        ).
      </div>
      {notice ? (
        <div className="banner" onClick={() => setNotice(null)} style={{ cursor: "pointer" }}>
          {notice} <span className="muted">(dismiss)</span>
        </div>
      ) : null}

      <section className="metrics">
        <Metric label="Working" value={String(activeWorkers ?? 0)} />
        <Metric label="Waiting" value={String(idleWorkers ?? 0)} />
        <Metric label="Drafts today" value={String(dailyStatus?.total ?? 0)} />
        <Metric label="Pending approval" value={String(dailyStatus?.pending_approval ?? pendingCount)} />
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Go live checklist</h2>
          <span className="muted">
            Drafts queue offline — paste env vars to send after Approve ·{" "}
            <Link className="linkish" to="/dashboard/integrations">
              Integrations
            </Link>
          </span>
        </div>
        {!goLive ? (
          <p className="muted waiting-copy">Loading integration status…</p>
        ) : (
          <>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              {goLive.ready_count}/{goLive.total} platforms configured. Approve a draft below → backend attempts a real
              send; missing keys return <code>configuration_required</code> with the exact vars needed.
            </p>
            <ul className="stat-list">
              {goLive.platforms.map((p: any) => (
                <li key={p.platform}>
                  <span>
                    {p.display_name}
                    {!p.configured && p.platform === "x_twitter" ? (
                      <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                        Needs OAuth + may require API credits
                      </span>
                    ) : null}
                    {!p.configured && (p.platform === "linkedin" || p.platform === "instagram" || p.platform === "threads") ? (
                      <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                        Needs credentials — drafts work offline
                      </span>
                    ) : null}
                  </span>
                  <strong>{p.configured ? "Ready to send" : "Needs credentials"}</strong>
                </li>
              ))}
            </ul>
            {goLive.platforms.some((p: any) => !p.configured) ? (
              <>
                {goLive.note ? (
                  <p className="muted" style={{ fontSize: "0.82rem", marginTop: "0.5rem" }}>
                    {goLive.note}
                  </p>
                ) : null}
                <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Platform</th>
                      <th>Paste into .env</th>
                    </tr>
                  </thead>
                  <tbody>
                    {goLive.platforms
                      .filter((p: any) => !p.configured)
                      .map((p: any) => (
                        <tr key={p.platform}>
                          <td className="mono">{p.platform}</td>
                          <td className="mono muted">{(p.env_vars || []).join(", ")}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              </>
            ) : null}
          </>
        )}
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Influencer research</h2>
          <span className="muted">Adrian · public web signals via multi_search + AI Gateway — no fake follower counts</span>
        </div>
        <form className="verify-form" onSubmit={onInfluencerResearch}>
          <input
            className="field"
            value={influencerQuery}
            onChange={(e) => setInfluencerQuery(e.target.value)}
            placeholder="Research query"
            required
          />
          <input
            className="field"
            value={influencerNiche}
            onChange={(e) => setInfluencerNiche(e.target.value)}
            placeholder="Niche (optional)"
          />
          <button className="btn btn-primary" type="submit" disabled={influencerBusy}>
            {influencerBusy ? "Researching…" : "Research creators"}
          </button>
        </form>
        {influencerResearch ? (
          <div style={{ marginTop: "0.85rem" }}>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              {influencerResearch.message}
              {influencerResearch.providers_used?.length
                ? ` · providers: ${(influencerResearch.providers_used || []).join(", ")}`
                : ""}
            </p>
            {influencerResearch.summary ? (
              <pre className="code-block" style={{ whiteSpace: "pre-wrap", maxHeight: 220, overflow: "auto" }}>
                {influencerResearch.summary}
              </pre>
            ) : null}
            {(influencerResearch.results || []).length > 0 ? (
              <ul className="plain-list" style={{ marginTop: "0.6rem" }}>
                {(influencerResearch.results || []).slice(0, 8).map((r: any, i: number) => (
                  <li key={`${r.url || r.title}-${i}`}>
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noreferrer">
                        {r.title || r.url}
                      </a>
                    ) : (
                      <span>{r.title || "Untitled"}</span>
                    )}
                    <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                      {(r.snippet || "").slice(0, 160)}
                      {(r.snippet || "").length > 160 ? "…" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : influencerResearch.status === "configuration_required" ? (
              <p className="muted waiting-copy">
                Set <code>VERIDIQ_TAVILY_API_KEY</code> / Exa / SerpAPI — research stays honest until then.
              </p>
            ) : null}
          </div>
        ) : null}
      </section>

      {lastApproveResult ? (
        <div className="banner">
          Approve result: <strong>{lastApproveResult.status}</strong>
          {lastApproveResult.message ? ` — ${lastApproveResult.message}` : ""}
          {lastApproveResult.send_attempt?.message ? ` (${lastApproveResult.send_attempt.message})` : ""}
        </div>
      ) : null}

      <section className="panel glass">
        <div className="panel-head">
          <h2>Marketing team</h2>
          <span className="muted">Human names, real roles — click Run now to queue drafts for your review</span>
        </div>
        {cards.length === 0 ? (
          <p className="muted waiting-copy">Loading team…</p>
        ) : (
          <div className="worker-grid">
            {cards.map((c) => (
              <div key={c.agent_type} className="worker-card glass">
                <div className="worker-card-head">
                  <AgentAvatar name={c.name} hue={c.avatar_hue} size={44} />
                  <div>
                    <strong>{c.name}</strong>
                    <span className="muted">{c.role}</span>
                    <span className="muted mono">{c.email}</span>
                  </div>
                  <span className={`pill ${c.status === "working" ? "ok" : ""}`}>{c.status_label}</span>
                </div>
                <div className="worker-card-body">
                  <p>{c.biography}</p>
                  <div className="skill-row">
                    {(c.skills || []).map((s: string) => (
                      <span key={s} className="skill-chip">
                        {s}
                      </span>
                    ))}
                  </div>
                  {c.status === "working" && c.current_task ? (
                    <p className="muted" style={{ fontSize: "0.82rem", marginTop: "0.4rem" }}>
                      {c.current_task}
                    </p>
                  ) : null}
                  {c.agent_type === "influencer_relations" ? (
                    <span className="pill ok" style={{ marginTop: "0.35rem", display: "inline-block" }}>
                      Influencer lead
                    </span>
                  ) : null}
                  <AgentControls agentType={c.agent_type} controlStatus={c.control_status} onChanged={() => void refreshTeam()} />
                  <Link
                    className="linkish"
                    to="/dashboard/runtime"
                    style={{ display: "inline-block", marginTop: "0.5rem", fontSize: "0.82rem" }}
                  >
                    Watch on Live Runtime →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Content queue</h2>
          <span className="muted">Every draft requires your approval before anything sends</span>
        </div>
        {queue.length === 0 ? (
          <EmptyState title="Queue is empty" body="Click Run now on any agent above (or Run marketing team now) to generate drafts." />
        ) : (
          <>
            <div className="main-actions" style={{ marginBottom: "0.6rem" }}>
              <button className="btn btn-primary btn-sm" type="button" disabled={queueBusy || pendingCount === 0} onClick={() => void onApproveAllPending()}>
                Approve all pending ({pendingCount}){pendingCount > 1 ? " — paced sends" : ""}
              </button>
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                disabled={queueBusy || pendingCount === 0}
                onClick={() => {
                  if (!window.confirm(`Clear old pending drafts (keep 20 most recent)?`)) return;
                  setQueueBusy(true);
                  void api
                    .marketingClearPending(campaignId || undefined, 20)
                    .then((r) => {
                      setNotice(r.message);
                      if (campaignId) return refreshCampaignQueue(campaignId);
                    })
                    .catch((err: any) => setError(err.message))
                    .finally(() => setQueueBusy(false));
                }}
              >
                Clear old drafts
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>Content</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((item) => (
                    <tr key={item.draft_id}>
                      <td className="mono">{channelFromKind(item.kind)}</td>
                      <td style={{ maxWidth: 420 }}>
                        <span className="muted">
                          {(item.body || "").slice(0, 140)}
                          {(item.body || "").length > 140 ? "…" : ""}
                        </span>
                      </td>
                      <td>
                        <span className={`pill ${draftStatusTone(item.external_action_status)}`}>
                          {item.external_action_status}
                        </span>
                      </td>
                      <td>
                        {item.external_action_status === "draft_only" ? (
                          <div style={{ display: "flex", gap: "0.4rem" }}>
                            <button type="button" className="linkish" disabled={queueBusy} onClick={() => void onApproveQueueItem(item, true)}>
                              Approve
                            </button>
                            <button type="button" className="linkish" disabled={queueBusy} onClick={() => void onApproveQueueItem(item, false)}>
                              Reject
                            </button>
                          </div>
                        ) : (
                          <span className="muted">{item.send_attempt?.message || "—"}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="panel glass">
        <button type="button" className="btn btn-ghost" onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? "Hide advanced tools ▲" : "Advanced: campaigns, comments &amp; creative tools ▾"}
        </button>
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: "0.4rem" }}>
          Everything above already runs against the default "Market VeriDiQ" campaign — open this only for a second
          campaign, one-off engagement replies, or Canva/video creative.
        </p>

        {showAdvanced ? (
          <div style={{ marginTop: "1rem" }}>
            <div className="two-col">
              <section className="panel glass">
                <h2>New campaign</h2>
                <form className="verify-form" onSubmit={onCreateCampaign}>
                  <input className="field" placeholder="Campaign name" value={name} onChange={(e) => setName(e.target.value)} required />
                  <textarea
                    className="field"
                    rows={3}
                    placeholder="Product brief (used to steer generated copy)"
                    value={brief}
                    onChange={(e) => setBrief(e.target.value)}
                  />
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    {CAMPAIGN_CHANNELS.map((c) => (
                      <label key={c} className="muted" style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
                        <input type="checkbox" checked={channels.includes(c)} onChange={() => toggleChannel(c)} />
                        {c}
                      </label>
                    ))}
                  </div>
                  <button className="btn btn-primary" type="submit" disabled={advBusy || !name.trim() || channels.length === 0}>
                    {advBusy ? "Creating…" : "Create campaign"}
                  </button>
                </form>
              </section>

              <section className="panel glass">
                <h2>Campaigns</h2>
                {campaigns.length === 0 ? (
                  <p className="muted waiting-copy">No campaigns yet — create one to get started.</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Status</th>
                          <th>Channels</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {campaigns.map((c) => (
                          <tr key={c.campaign_id}>
                            <td>{c.name}</td>
                            <td>
                              <span className={`pill ${c.status === "active" ? "ok" : ""}`}>{c.status}</span>
                            </td>
                            <td className="muted">{(c.channels || []).join(", ")}</td>
                            <td>
                              <button type="button" className="linkish" onClick={() => setAdvSelectedId(c.campaign_id)}>
                                Open
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>

            {advDetail ? (
              <section className="panel glass">
                <h2>Campaign — {advDetail.name}</h2>
                <ul className="stat-list">
                  <li>
                    <span>Status</span>
                    <strong>{advDetail.status}</strong>
                  </li>
                  <li>
                    <span>Channels</span>
                    <strong>{(advDetail.channels || []).join(", ")}</strong>
                  </li>
                  <li>
                    <span>Last generated</span>
                    <strong>{advDetail.last_generated_date || "never"}</strong>
                  </li>
                </ul>

                <div className="main-actions" style={{ margin: "0.85rem 0" }}>
                  <button className="btn btn-primary" type="button" disabled={advBusy || advDetail.status !== "active"} onClick={() => void onRunDaily()}>
                    Run today's content pack
                  </button>
                  {advDetail.status === "active" ? (
                    <button className="btn btn-ghost" type="button" disabled={advBusy} onClick={() => void onSetStatus("paused")}>
                      Pause campaign
                    </button>
                  ) : (
                    <button className="btn btn-ghost" type="button" disabled={advBusy} onClick={() => void onSetStatus("active")}>
                      Activate campaign
                    </button>
                  )}
                </div>

                <h3 className="subh">Content queue</h3>
                {advQueue.length === 0 ? (
                  <EmptyState title="Queue is empty" body="Run today's content pack to generate drafts for this campaign." />
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Channel</th>
                          <th>Content</th>
                          <th>Status</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {advQueue.map((item) => (
                          <tr key={item.draft_id}>
                            <td className="mono">{channelFromKind(item.kind)}</td>
                            <td style={{ maxWidth: 420 }}>
                              <span className="muted">
                                {(item.body || "").slice(0, 140)}
                                {(item.body || "").length > 140 ? "…" : ""}
                              </span>
                            </td>
                            <td>
                              <span className={`pill ${draftStatusTone(item.external_action_status)}`}>{item.external_action_status}</span>
                            </td>
                            <td>
                              {item.external_action_status === "draft_only" ? (
                                <div style={{ display: "flex", gap: "0.4rem" }}>
                                  <button type="button" className="linkish" disabled={advBusy} onClick={() => void onApproveAdvQueueItem(item, true)}>
                                    Approve
                                  </button>
                                  <button type="button" className="linkish" disabled={advBusy} onClick={() => void onApproveAdvQueueItem(item, false)}>
                                    Reject
                                  </button>
                                </div>
                              ) : (
                                <span className="muted">{item.send_attempt?.message || "—"}</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ) : null}

            <div className="two-col">
              <section className="panel glass">
                <h2>Engagement comment</h2>
                <p className="muted" style={{ fontSize: "0.85rem" }}>
                  Adrian (influencer) humanized reply drafts — generate offline, then approve to attempt a real API reply.
                  X and Telegram support replies via official APIs; LinkedIn/Instagram report platform limits honestly.
                </p>
                <form className="verify-form" onSubmit={onDraftComment}>
                  <select className="field" value={commentChannel} onChange={(e) => setCommentChannel(e.target.value)}>
                    {COMMENT_CHANNELS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <button className="btn btn-ghost btn-sm" type="button" disabled={advBusy} onClick={() => void onGenerateComment()}>
                    Generate Adrian reply
                  </button>
                  <input
                    className="field"
                    placeholder="Target ref (tweet id / post URN / comment id / chat_id[:message_id])"
                    value={commentTarget}
                    onChange={(e) => setCommentTarget(e.target.value)}
                  />
                  <textarea className="field" rows={3} value={commentText} onChange={(e) => setCommentText(e.target.value)} required />
                  <button className="btn btn-primary" type="submit" disabled={advBusy}>
                    Draft comment
                  </button>
                </form>
                {commentDraft ? (
                  <div style={{ marginTop: "0.85rem" }}>
                    <p className="muted">
                      Status: <strong>{commentDraft.external_action_status}</strong>
                    </p>
                    <div className="main-actions">
                      <button className="btn btn-primary" type="button" disabled={advBusy} onClick={() => void onApproveComment(true)}>
                        Approve &amp; attempt send
                      </button>
                      <button className="btn btn-ghost" type="button" disabled={advBusy} onClick={() => void onApproveComment(false)}>
                        Reject
                      </button>
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="panel glass">
                <h2>Canva creative</h2>
                <form className="verify-form" onSubmit={onCreateDesign}>
                  <input className="field" value={canvaTitle} onChange={(e) => setCanvaTitle(e.target.value)} required />
                  <button className="btn btn-primary" type="submit" disabled={advBusy}>
                    Create Canva design
                  </button>
                </form>
                {canvaResult ? (
                  <p className="muted" style={{ marginTop: "0.85rem" }}>
                    {canvaResult.status === "ok" ? (
                      <>
                        Design created —{" "}
                        <a href={canvaResult.edit_url} target="_blank" rel="noreferrer">
                          open in Canva
                        </a>
                      </>
                    ) : (
                      canvaResult.message
                    )}
                  </p>
                ) : null}
              </section>
            </div>

            <section className="panel glass">
              <h2>Video storyboard</h2>
              <p className="muted" style={{ fontSize: "0.85rem" }}>
                Always generates a real script + shot list offline. Rendering an actual MP4 requires an optional configured
                render provider — otherwise reports <code>configuration_required</code> honestly.
              </p>
              <form className="verify-form" style={{ flexDirection: "row", flexWrap: "wrap", gap: "0.5rem" }} onSubmit={onCreateStoryboard}>
                <select className="field" value={storyFeature} onChange={(e) => setStoryFeature(e.target.value)}>
                  {Object.keys(features?.features || { truth_verification: 1 }).map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
                <input
                  className="field"
                  type="number"
                  min={15}
                  max={120}
                  value={storyDuration}
                  onChange={(e) => setStoryDuration(Number(e.target.value))}
                  style={{ maxWidth: 120 }}
                />
                <button className="btn btn-primary" type="submit" disabled={advBusy}>
                  Generate storyboard
                </button>
              </form>

              {storyboard ? (
                <div style={{ marginTop: "0.85rem" }}>
                  <h3 className="subh">{storyboard.title}</h3>
                  <pre className="draft-body">{storyboard.script}</pre>
                  <ul className="stat-list">
                    {storyboard.shot_list.map((s: any) => (
                      <li key={s.scene}>
                        <span>Scene {s.scene}</span>
                        <strong>{s.shot}</strong>
                      </li>
                    ))}
                  </ul>
                  <p className="muted">
                    Artifact saved to: <span className="mono">{storyboard.artifact_path}</span>
                  </p>
                  <button className="btn btn-ghost" type="button" disabled={advBusy} onClick={() => void onRenderVideo()}>
                    Attempt render
                  </button>
                  {renderResult ? (
                    <p className="muted" style={{ marginTop: "0.5rem" }}>
                      Render: <strong>{renderResult.status}</strong> — {renderResult.message}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>
        ) : null}
      </section>
    </AppShell>
  );
}
