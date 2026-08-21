const API_BASE = import.meta.env.VITE_API_BASE || "";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("veridiq_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Tracks the most recent 429 so callers can back off instead of hammering the
// API the instant a poll interval fires again. This is a soft client-side
// circuit breaker, not a replacement for the server-side rate limit.
let rateLimitedUntil = 0;

function isRateLimited(): boolean {
  return Date.now() < rateLimitedUntil;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (isRateLimited()) {
    throw new Error(`429 ${path}: rate limited, backing off`);
  }
  const started = performance.now();
  const method = (init?.method || "GET").toUpperCase();
  const headers: HeadersInit = { ...authHeaders(), ...(init?.headers || {}) };
  // Only send a JSON Content-Type when there's actually a JSON body. Setting
  // it on plain GETs makes every poll a "non-simple" CORS request, forcing an
  // OPTIONS preflight round-trip for every single call — silently doubling
  // real request volume against the server-side rate limiter.
  if (init?.body !== undefined && !(init.headers && "Content-Type" in init.headers)) {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, method, headers });
  const latency = Math.round(performance.now() - started);
  if (response.status === 429) {
    const retryAfterHeader = response.headers.get("Retry-After");
    const retryAfterSec = retryAfterHeader ? Number(retryAfterHeader) : 5;
    rateLimitedUntil = Date.now() + Math.max(2, Number.isFinite(retryAfterSec) ? retryAfterSec : 5) * 1000;
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${path}: ${text}`);
  }
  const data = (await response.json()) as T & { _latencyMs?: number };
  data._latencyMs = latency;
  return data;
}

export type JobEvent = {
  job_id?: string;
  stage: string;
  message?: string;
  timestamp?: string;
  truth_score?: number;
  agent_type?: string;
};

export function subscribeJobEvents(
  jobUuid: string,
  onEvent: (event: JobEvent) => void,
  onDone?: () => void
): () => void {
  const url = `${API_BASE}/api/v1/veridiq/jobs/${jobUuid}/events`;
  const source = new EventSource(url);
  source.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as JobEvent;
      onEvent(data);
      if (data.stage === "completed" || data.stage === "failed" || data.stage === "stream_end") {
        source.close();
        onDone?.();
      }
    } catch {
      /* ignore malformed */
    }
  };
  source.onerror = () => {
    source.close();
    onDone?.();
  };
  return () => source.close();
}

export type WorkforceSnapshot = {
  type: string;
  roster: any;
  cards: any[];
  departments: any[];
  active_assignments: any[];
  collaboration: any[];
  platform_activity?: any[];
  pending_drafts_count?: number;
  pending_drafts?: any[];
  sdk_tasks?: any[];
  waiting_for_tasks?: boolean;
  timestamp?: string;
};

/**
 * Subscribe to the live workforce SSE stream. Calls onSnapshot with each
 * pushed roster snapshot; calls onError once if the stream drops so the
 * caller can fall back to polling.
 */
export function subscribeWorkforceEvents(
  onSnapshot: (data: WorkforceSnapshot) => void,
  onError?: () => void
): () => void {
  const url = `${API_BASE}/api/v1/veridiq/workforce/events`;
  const source = new EventSource(url);
  let closed = false;
  source.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as WorkforceSnapshot;
      onSnapshot(data);
    } catch {
      /* ignore malformed */
    }
  };
  source.onerror = () => {
    if (closed) return;
    closed = true;
    source.close();
    onError?.();
  };
  return () => {
    closed = true;
    source.close();
  };
}

export const api = {
  brand: () => request<any>("/api/v1/brand"),
  health: () => request<any>("/api/v1/health"),
  system: () => request<any>("/api/v1/veridiq/system"),
  connectivity: () => request<any>("/api/v1/veridiq/agents/connectivity"),
  dashboard: () => request<any>("/api/v1/veridiq/dashboard"),
  agents: () => request<any>("/api/v1/veridiq/agents"),
  agent: (agentType: string) => request<any>(`/api/v1/veridiq/agents/${agentType}`),
  workforce: () => request<any>("/api/v1/veridiq/workforce"),
  workforceRoster: (department?: string, q?: string) => {
    const params = new URLSearchParams();
    if (department) params.set("department", department);
    if (q) params.set("q", q);
    const qs = params.toString();
    return request<any>(`/api/v1/veridiq/workforce/roster${qs ? `?${qs}` : ""}`);
  },
  workspace: () => request<any>("/api/v1/veridiq/workspace"),
  workspaceAgent: (agentType: string) => request<any>(`/api/v1/veridiq/workspace/${agentType}`),
  integrations: () => request<any>("/api/v1/veridiq/integrations"),
  integrationDetail: (platform: string) => request<any>(`/api/v1/veridiq/integrations/${platform}`),
  integrationTest: (platform: string) =>
    request<any>(`/api/v1/veridiq/integrations/${platform}/test`, { method: "POST" }),
  integrationsActivity: (opts?: { agentType?: string; platform?: string; limit?: number }) => {
    const params = new URLSearchParams();
    if (opts?.agentType) params.set("agent_type", opts.agentType);
    if (opts?.platform) params.set("platform", opts.platform);
    if (opts?.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return request<any>(`/api/v1/veridiq/integrations/activity${qs ? `?${qs}` : ""}`);
  },
  threadsOAuthAuthorizeUrl: () =>
    request<{ authorize_url: string; redirect_uri: string; client_id: string }>(
      "/api/v1/veridiq/integrations/threads/oauth/authorize-url"
    ),
  threadsOAuthExchange: (body: { code: string; write_env?: boolean; long_lived?: boolean }) =>
    request<any>("/api/v1/veridiq/integrations/threads/oauth/exchange", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  telegramWebAppAuth: (body: { init_data: string; issue_session?: boolean; max_age_sec?: number }) =>
    request<{
      ok: boolean;
      user?: {
        id?: number;
        first_name?: string;
        last_name?: string;
        username?: string;
        language_code?: string;
        is_premium?: boolean;
        photo_url?: string;
      };
      session_user?: { id: number; email: string; full_name: string; role: string; auth_provider?: string };
      access_token?: string;
      token_type?: string;
      auth_date?: number;
      query_id?: string;
    }>("/api/v1/veridiq/telegram/webapp/auth", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  telegramMiniAppStatus: () =>
    request<{ configured: boolean; miniapp_url?: string; message: string }>(
      "/api/v1/veridiq/telegram/miniapp"
    ),
  ops: () => request<any>("/api/v1/veridiq/ops"),
  commandCenter: () => request<any>("/api/v1/veridiq/command-center"),
  collaboration: (jobId?: string) =>
    request<any>(`/api/v1/veridiq/collaboration${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`),
  departments: () => request<any>("/api/v1/veridiq/departments"),
  market: () => request<any>("/api/v1/veridiq/market"),
  marketHistory: (coinId: string, days = 7) =>
    request<any>(`/api/v1/veridiq/market/history/${encodeURIComponent(coinId)}?days=${days}`),
  liveRequest: (text: string, opts?: { title?: string; async_mode?: boolean; coin_id?: string }) =>
    request<any>("/api/v1/veridiq/requests", {
      method: "POST",
      body: JSON.stringify({
        text,
        title: opts?.title || "Live AI request",
        async_mode: opts?.async_mode ?? true,
        coin_id: opts?.coin_id || "bitcoin",
      }),
    }),
  orchestratorPlan: (text: string) =>
    request<any>(`/api/v1/veridiq/orchestrator/plan?text=${encodeURIComponent(text)}`),
  commsDraft: (kind: string, context: string, recipient_hint = "") =>
    request<any>("/api/v1/veridiq/comms/draft", {
      method: "POST",
      body: JSON.stringify({ kind, context, recipient_hint }),
    }),
  commsApprove: (draft_id: string, approved: boolean, channel = "email") =>
    request<any>("/api/v1/veridiq/comms/approve", {
      method: "POST",
      body: JSON.stringify({ draft_id, approved, channel }),
    }),
  commsApproveBatch: (
    drafts: Array<{ draft_id: string; channel: string }>,
    approved = true,
    cadence?: boolean
  ) =>
    request<any>("/api/v1/veridiq/comms/approve-batch", {
      method: "POST",
      body: JSON.stringify({ drafts, approved, cadence }),
    }),
  verifyMetrics: () => request<any>("/api/v1/veridiq/pages/verify-metrics"),
  newsMetrics: () => request<any>("/api/v1/veridiq/pages/news-metrics"),
  meetingMetrics: () => request<any>("/api/v1/veridiq/pages/meeting-metrics"),
  reportsMetrics: () => request<any>("/api/v1/veridiq/pages/reports-metrics"),
  connectors: () => request<any>("/api/v1/veridiq/connectors"),
  connectorJobs: () => request<any>("/api/v1/veridiq/connectors/jobs"),
  connectorNews: () => request<any>("/api/v1/veridiq/connectors/news"),
  jobs: () => request<any>("/api/v1/veridiq/jobs"),
  job: (id: string) => request<any>(`/api/v1/veridiq/jobs/${id}`),
  verify: (text: string, title = "VERIDIQ Verification", async_mode = false) =>
    request<any>("/api/v1/veridiq/verify", {
      method: "POST",
      body: JSON.stringify({ text, title, async_mode }),
    }),
  orchestrate: (text: string) =>
    request<any>("/api/v1/veridiq/orchestrate", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  // Non-blocking "Run" — returns { status: "started", run_id, poll } immediately;
  // the agent executes on a background worker and stays visibly "working" on the
  // Agent Workspace / workforce SSE stream for the run's real duration.
  runAgent: (agentType: string, payload: Record<string, unknown> = {}) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/run`, {
      method: "POST",
      body: JSON.stringify({ payload }),
    }),
  runResult: (agentType: string, runId: string) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/runs/${runId}`),
  login: (email: string, password: string) =>
    request<any>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string, full_name = "") =>
    request<any>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    }),
  clerkStatus: () => request<any>("/api/v1/auth/clerk/status"),
  clerkSync: (clerkToken: string, profile: { email?: string; full_name?: string } = {}) =>
    request<any>("/api/v1/auth/clerk/sync", {
      method: "POST",
      headers: { Authorization: `Bearer ${clerkToken}` },
      body: JSON.stringify({
        email: profile.email || "",
        full_name: profile.full_name || "",
      }),
    }),
  me: () => request<any>("/api/v1/auth/me"),
  hostChat: (question: string) =>
    request<any>("/api/v1/veridiq/host/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  blockchainStatus: () => request<any>("/api/v1/blockchain/status"),
  attest: (job_id: string) =>
    request<any>("/api/v1/blockchain/attest", {
      method: "POST",
      body: JSON.stringify({ job_id }),
    }),
  runtimeJobs: (limit = 20) => request<any>(`/api/v1/veridiq/runtime/jobs?limit=${limit}`),
  runtimeStatus: () => request<any>("/api/v1/veridiq/runtime/status"),
  runtimeBrowserSession: (url: string, jobId?: string, agentType?: string) =>
    request<any>("/api/v1/veridiq/runtime/browser-session", {
      method: "POST",
      body: JSON.stringify({ url, job_id: jobId, agent_type: agentType }),
    }),
  runtimeBrowserSessionImageUrl: (sessionId: string) =>
    `${API_BASE}/api/v1/veridiq/runtime/browser-session/${sessionId}`,
  runtimeVisualProof: (limit = 12) =>
    request<any>(`/api/v1/veridiq/runtime/visual-proof?limit=${limit}`),
  callingAgent: () => request<any>("/api/v1/veridiq/calling/agent"),
  callingAgentCommand: (message: string, history?: { role: string; text: string }[]) =>
    request<any>("/api/v1/veridiq/calling/agent", {
      method: "POST",
      body: JSON.stringify({ message, history: history || [] }),
    }),
  postingsAgent: () => request<any>("/api/v1/veridiq/postings/agent"),
  postingsAgentCommand: (
    message: string,
    history?: { role: string; text: string }[],
    init?: RequestInit,
    attachments?: string[],
    chatId?: string,
  ) =>
    request<any>("/api/v1/veridiq/postings/agent", {
      method: "POST",
      body: JSON.stringify({
        message,
        history: history || [],
        attachments: attachments || [],
        chat_id: chatId || "",
      }),
      ...init,
    }),
  postingsChats: (limit = 80) =>
    request<any>(`/api/v1/veridiq/postings/chats?limit=${limit}`),
  postingsChatCreate: (title = "") =>
    request<any>("/api/v1/veridiq/postings/chats", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  postingsChatGet: (chatId: string) =>
    request<any>(`/api/v1/veridiq/postings/chats/${encodeURIComponent(chatId)}`),
  postingsChatDelete: (chatId: string) =>
    request<any>(`/api/v1/veridiq/postings/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    }),
  postingsUpload: async (files: File | File[]) => {
    const list = Array.isArray(files) ? files : [files];
    const fd = new FormData();
    for (const f of list) {
      fd.append("files", f);
    }
    const response = await fetch(`${API_BASE}/api/v1/veridiq/postings/upload`, {
      method: "POST",
      headers: { ...authHeaders() },
      body: fd,
    });
    if (!response.ok) {
      throw new Error(`${response.status} postings/upload: ${await response.text()}`);
    }
    return (await response.json()) as {
      ok: boolean;
      count: number;
      uploads: Array<{
        filename: string;
        url: string;
        path: string;
        relative_path: string;
        size: number;
      }>;
      urls: string[];
      paths: string[];
      filenames: string[];
    };
  },
  postingsVideoJob: (jobId: string, init?: RequestInit) =>
    request<any>(`/api/v1/veridiq/postings/video/jobs/${encodeURIComponent(jobId)}`, init),
  postingsFeedback: (body: {
    thumbs?: "up" | "down";
    rating?: number;
    prompt?: string;
    style?: string;
    media_url?: string;
    media_type?: string;
    chat_id?: string;
    topic?: string;
    notes?: string;
  }) =>
    request<any>("/api/v1/veridiq/postings/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  postingsFeedbackStats: () =>
    request<any>("/api/v1/veridiq/postings/feedback/stats"),
  postingsLearning: () => request<any>("/api/v1/veridiq/postings/learning"),
  // LiveKit meetings hub + live Collaboration Hub
  callingHub: () => request<any>("/api/v1/veridiq/calling/meetings/hub"),
  callingHubEnter: () =>
    request<any>("/api/v1/veridiq/calling/meetings/hub/enter", { method: "POST", body: "{}" }),
  callingHubStartConversation: (force = false) =>
    request<any>(
      `/api/v1/veridiq/calling/meetings/hub/start-conversation?force=${force ? "true" : "false"}`,
      { method: "POST", body: "{}" }
    ),
  callingHubMessage: (body: string, meetingId?: string, threadId?: string) =>
    request<any>("/api/v1/veridiq/calling/meetings/hub/messages", {
      method: "POST",
      body: JSON.stringify({
        body,
        meeting_id: meetingId || "",
        thread_id: threadId || "",
      }),
    }),
  callingHubThreads: () => request<any>("/api/v1/veridiq/calling/hub/threads"),
  callingHubThread: (id: string) => request<any>(`/api/v1/veridiq/calling/hub/threads/${id}`),
  callingHubDms: () => request<any>("/api/v1/veridiq/calling/hub/dms"),
  callingHubOpenDm: (agentType: string) =>
    request<any>("/api/v1/veridiq/calling/hub/dms/open", {
      method: "POST",
      body: JSON.stringify({ agent_type: agentType }),
    }),
  callingHubInvites: () => request<any>("/api/v1/veridiq/calling/hub/invites"),
  callingHubAcceptInvite: (inviteId: string) =>
    request<any>(`/api/v1/veridiq/calling/hub/invites/${inviteId}/accept`, {
      method: "POST",
      body: "{}",
    }),
  callingHubDeclineInvite: (inviteId: string) =>
    request<any>(`/api/v1/veridiq/calling/hub/invites/${inviteId}/decline`, {
      method: "POST",
      body: "{}",
    }),
  callingRequestPersonalMeeting: (specialist_query: string, topic?: string) =>
    request<any>("/api/v1/veridiq/calling/hub/request-personal-meeting", {
      method: "POST",
      body: JSON.stringify({ specialist_query, topic: topic || "" }),
    }),
  callingMeetings: () => request<any>("/api/v1/veridiq/calling/meetings"),
  callingMeeting: (id: string) => request<any>(`/api/v1/veridiq/calling/meetings/${id}`),
  callingScheduleMeeting: (payload: {
    topic: string;
    scheduled_at_pkt: string;
    agenda?: string[];
    agent_types?: string[];
  }) =>
    request<any>("/api/v1/veridiq/calling/meetings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  callingStartMeeting: (id: string) =>
    request<any>(`/api/v1/veridiq/calling/meetings/${id}/start`, { method: "POST", body: "{}" }),
  callingRequestJoin: (id: string) =>
    request<any>(`/api/v1/veridiq/calling/meetings/${id}/request-join`, { method: "POST", body: "{}" }),
  callingConfirmJoin: (id: string, yes = true) =>
    request<any>(`/api/v1/veridiq/calling/meetings/${id}/confirm-join`, {
      method: "POST",
      body: JSON.stringify({ yes }),
    }),
  callingEndMeeting: (id: string) =>
    request<any>(`/api/v1/veridiq/calling/meetings/${id}/end`, { method: "POST", body: "{}" }),
  callingLivekitToken: (payload: {
    meeting_id: string;
    identity?: string;
    name?: string;
    role?: string;
  }) =>
    request<any>("/api/v1/veridiq/calling/livekit/token", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  callingLivekitStatus: () => request<any>("/api/v1/veridiq/calling/livekit/status"),
  callingAgoraStatus: () => request<any>("/api/v1/veridiq/calling/agora/status"),
  callingBudget: (userKey = "default") =>
    request<any>(`/api/v1/veridiq/calling/budget?user_key=${encodeURIComponent(userKey)}`),
  callingBudgetReset: (userKey = "default") =>
    request<any>(`/api/v1/veridiq/calling/budget/reset?user_key=${encodeURIComponent(userKey)}`, {
      method: "POST",
      body: "{}",
    }),
  callingTimedSessions: (opts?: { status?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set("status", opts.status);
    if (opts?.limit) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<any>(`/api/v1/veridiq/calling/timed${qs ? `?${qs}` : ""}`);
  },
  callingScheduleTimed: (payload: {
    purpose?: string;
    script?: string;
    requested_seconds?: number;
    auto_start?: boolean;
    user_key?: string;
  }) =>
    request<any>("/api/v1/veridiq/calling/timed", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  callingTimedActivate: (sessionId: string) =>
    request<any>(`/api/v1/veridiq/calling/timed/${encodeURIComponent(sessionId)}/activate`, {
      method: "POST",
      body: "{}",
    }),
  callingTimedCancelUncharged: (sessionId: string) =>
    request<any>(`/api/v1/veridiq/calling/timed/${encodeURIComponent(sessionId)}/cancel-uncharged`, {
      method: "POST",
      body: "{}",
    }),
  callingTimedEnd: (sessionId: string, reason = "completed") =>
    request<any>(
      `/api/v1/veridiq/calling/timed/${encodeURIComponent(sessionId)}/end?reason=${encodeURIComponent(reason)}`,
      { method: "POST", body: "{}" },
    ),
  callingMeetingEnter: (
    id: string,
    payload?: { identity?: string; name?: string; user_key?: string },
  ) =>
    request<any>(`/api/v1/veridiq/calling/meetings/${id}/enter`, {
      method: "POST",
      body: JSON.stringify(payload || { name: "You", identity: `user-${Date.now().toString(36)}` }),
    }),
  callingAgentPresence: (id: string, userKey = "default") =>
    request<any>(
      `/api/v1/veridiq/calling/meetings/${id}/agent-presence?user_key=${encodeURIComponent(userKey)}`,
      { method: "POST", body: "{}" },
    ),
  callingMeetingQuick: (payload: {
    topic?: string;
    scheduled_at_pkt?: string;
    agenda?: string[];
    name?: string;
  }) =>
    request<any>("/api/v1/veridiq/calling/meetings/quick", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  callingHubCompose: (body: string, threadId?: string) =>
    request<any>("/api/v1/veridiq/calling/meetings/hub/messages", {
      method: "POST",
      body: JSON.stringify({ body, thread_id: threadId || "", meeting_id: "" }),
    }),
  callingPipelineHealth: () => request<any>("/api/v1/veridiq/agents/pipeline/health"),
  callingAgoraToken: (payload: {
    channel: string;
    uid?: number | string;
    identity?: string;
    role?: string;
    ttl_sec?: number;
  }) =>
    request<any>("/api/v1/veridiq/calling/agora/token", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  // Legacy Twilio campaign routes (kept for API/tests)
  callingCampaigns: () => request<any>("/api/v1/veridiq/calling/campaigns"),
  callingCampaign: (id: string) => request<any>(`/api/v1/veridiq/calling/campaigns/${id}`),
  callingCreate: (payload: { to_number: string; purpose?: string; script: string; contact_name?: string }) =>
    request<any>("/api/v1/veridiq/calling/campaigns", { method: "POST", body: JSON.stringify(payload) }),
  callingApprove: (id: string, approved: boolean) =>
    request<any>(`/api/v1/veridiq/calling/campaigns/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  callingSummary: (id: string, summary: string) =>
    request<any>(`/api/v1/veridiq/calling/campaigns/${id}/summary`, {
      method: "POST",
      body: JSON.stringify({ summary }),
    }),
  callingFollowup: (id: string, recipientEmail: string) =>
    request<any>(`/api/v1/veridiq/calling/campaigns/${id}/followup`, {
      method: "POST",
      body: JSON.stringify({ recipient_email: recipientEmail }),
    }),
  // Agent↔agent meetings (hub propose → approve → countdown → LiveKit)
  agentMeetings: (opts?: { status?: string; thread_id?: string }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set("status", opts.status);
    if (opts?.thread_id) q.set("thread_id", opts.thread_id);
    const qs = q.toString();
    return request<any>(`/api/v1/veridiq/calling/agent-meetings${qs ? `?${qs}` : ""}`);
  },
  agentMeeting: (proposalId: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}`),
  agentMeetingPropose: (payload: {
    proposer_agent?: string;
    invitee_agent?: string;
    topic?: string;
    thread_id?: string;
    countdown?: number;
  }) =>
    request<any>("/api/v1/veridiq/calling/agent-meetings/propose", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  agentMeetingApprove: (proposalId: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/approve`, {
      method: "POST",
      body: "{}",
    }),
  agentMeetingDecline: (proposalId: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/decline`, {
      method: "POST",
      body: "{}",
    }),
  agentMeetingStart: (proposalId: string, force = false) =>
    request<any>(
      `/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/start?force=${force ? "true" : "false"}`,
      { method: "POST", body: "{}" },
    ),
  agentMeetingInviteAgent: (proposalId: string, agentType: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/invite-agent`, {
      method: "POST",
      body: JSON.stringify({ agent_type: agentType }),
    }),
  agentMeetingExtend: (proposalId: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/extend`, {
      method: "POST",
      body: "{}",
    }),
  agentMeetingEnd: (proposalId: string) =>
    request<any>(`/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/end`, {
      method: "POST",
      body: "{}",
    }),
  agentMeetingSpectator: (proposalId: string, name = "Spectator") =>
    request<any>(
      `/api/v1/veridiq/calling/agent-meetings/${encodeURIComponent(proposalId)}/spectator?name=${encodeURIComponent(name)}`,
      { method: "POST", body: "{}" },
    ),
  agentMeetingExternalJoin: (payload: { url: string; instructions?: string; thread_id?: string }) =>
    request<any>("/api/v1/veridiq/calling/agent-meetings/external-join", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadVerify: async (form: FormData) => {
    const started = performance.now();
    const response = await fetch(`${API_BASE}/api/v1/veridiq/verify/upload`, {
      method: "POST",
      headers: { ...authHeaders() },
      body: form,
    });
    if (!response.ok) throw new Error(`${response.status} upload: ${await response.text()}`);
    const data = await response.json();
    data._latencyMs = Math.round(performance.now() - started);
    return data;
  },
  reportUrl: (jobUuid: string) => `${API_BASE}/api/v1/veridiq/jobs/${jobUuid}/report`,
  homeOverview: () => request<any>("/api/v1/veridiq/home-overview"),

  // Agent control / runtime layer (Task 1)
  controlOverview: () => request<any>("/api/v1/veridiq/control"),
  agentControl: (agentType: string) => request<any>(`/api/v1/veridiq/agents/${agentType}/control`),
  agentControlStart: (agentType: string) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/start`, { method: "POST" }),
  agentControlStop: (agentType: string) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/stop`, { method: "POST" }),
  agentControlPause: (agentType: string) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/pause`, { method: "POST" }),
  agentControlResume: (agentType: string) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/resume`, { method: "POST" }),
  agentControlCommand: (agentType: string, command: string, payload?: Record<string, unknown>) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/command`, {
      method: "POST",
      body: JSON.stringify({ command, payload }),
    }),
  agentControlAssign: (agentType: string, campaign_type: string, payload?: Record<string, unknown>) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/control/assign`, {
      method: "POST",
      body: JSON.stringify({ campaign_type, payload }),
    }),

  // "Run Agent Test" admin capability (Task 2)
  agentTestRun: (agentType: string, platform?: string, payload?: Record<string, unknown>) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/test`, {
      method: "POST",
      body: JSON.stringify({ platform, payload }),
    }),
  agentTestHistory: (agentType: string, limit = 20) =>
    request<any>(`/api/v1/veridiq/agents/${agentType}/test/history?limit=${limit}`),
  agentTestsRecent: (limit = 50) => request<any>(`/api/v1/veridiq/agent-tests?limit=${limit}`),

  // Marketing Agency
  marketingFeatures: () => request<any>("/api/v1/veridiq/marketing/features"),
  marketingCampaigns: (status?: string) =>
    request<any>(`/api/v1/veridiq/marketing/campaigns${status ? `?status=${status}` : ""}`),
  marketingCampaignCreate: (payload: { name: string; product_brief?: string; channels?: string[] }) =>
    request<any>("/api/v1/veridiq/marketing/campaigns", { method: "POST", body: JSON.stringify(payload) }),
  marketingCampaignDetail: (campaignId: string) =>
    request<any>(`/api/v1/veridiq/marketing/campaigns/${campaignId}`),
  marketingCampaignStatus: (campaignId: string, status: string) =>
    request<any>(`/api/v1/veridiq/marketing/campaigns/${campaignId}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  marketingDailyRun: (campaign_id: string, channels?: string[], features?: string[]) =>
    request<any>("/api/v1/veridiq/marketing/daily/run", {
      method: "POST",
      body: JSON.stringify({ campaign_id, channels, features }),
    }),
  marketingDailyStatus: (campaignId?: string) =>
    request<any>(`/api/v1/veridiq/marketing/daily/status${campaignId ? `?campaign_id=${campaignId}` : ""}`),
  marketingQueue: (opts?: { campaignId?: string; channel?: string; status?: string; limit?: number }) => {
    const params = new URLSearchParams();
    if (opts?.campaignId) params.set("campaign_id", opts.campaignId);
    if (opts?.channel) params.set("channel", opts.channel);
    if (opts?.status) params.set("status", opts.status);
    if (opts?.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return request<any>(`/api/v1/veridiq/marketing/queue${qs ? `?${qs}` : ""}`);
  },
  marketingTeam: () => request<any>("/api/v1/veridiq/marketing/team"),
  marketingDefaultCampaign: () => request<any>("/api/v1/veridiq/marketing/default-campaign"),
  marketingRunNow: () => request<any>("/api/v1/veridiq/marketing/run-now", { method: "POST" }),
  marketingGoLiveChecklist: () => request<any>("/api/v1/veridiq/marketing/go-live-checklist"),
  influencerResearch: (payload: { query: string; niche?: string; max_results?: number; summarize?: boolean }) =>
    request<any>("/api/v1/veridiq/influencer/research", { method: "POST", body: JSON.stringify(payload) }),
  marketingClearPending: (campaignId?: string, keepRecent = 20) => {
    const params = new URLSearchParams();
    if (campaignId) params.set("campaign_id", campaignId);
    params.set("keep_recent", String(keepRecent));
    return request<any>(`/api/v1/veridiq/marketing/queue/clear-pending?${params.toString()}`, { method: "POST" });
  },
  marketingTeamAssign: (agent_type: string, campaign_id?: string, channels?: string[]) =>
    request<any>("/api/v1/veridiq/marketing/team/assign", {
      method: "POST",
      body: JSON.stringify({ agent_type, campaign_id, channels }),
    }),
  marketingComment: (payload: {
    channel: string;
    text?: string;
    target_ref?: string;
    campaign_id?: string;
    feature?: string;
    agent_type?: string;
  }) => request<any>("/api/v1/veridiq/marketing/comments", { method: "POST", body: JSON.stringify(payload) }),
  marketingCommentPreview: (params: { channel: string; feature?: string; agent_type?: string }) => {
    const q = new URLSearchParams();
    q.set("channel", params.channel);
    if (params.feature) q.set("feature", params.feature);
    if (params.agent_type) q.set("agent_type", params.agent_type);
    return request<any>(`/api/v1/veridiq/marketing/comments/preview?${q.toString()}`);
  },
  marketingCanvaStatus: () => request<any>("/api/v1/veridiq/marketing/canva/status"),
  marketingCanvaDesign: (payload: { title: string; design_type?: string; width?: number; height?: number }) =>
    request<any>("/api/v1/veridiq/marketing/canva/design", { method: "POST", body: JSON.stringify(payload) }),
  marketingStoryboardCreate: (payload: {
    campaign_id?: string;
    feature?: string;
    style?: string;
    duration_sec?: number;
    product_brief?: string;
  }) => request<any>("/api/v1/veridiq/marketing/video/storyboard", { method: "POST", body: JSON.stringify(payload) }),
  marketingStoryboardGet: (storyboardId: string) =>
    request<any>(`/api/v1/veridiq/marketing/video/storyboard/${storyboardId}`),
  marketingVideoRender: (storyboardId: string) =>
    request<any>("/api/v1/veridiq/marketing/video/render", {
      method: "POST",
      body: JSON.stringify({ storyboard_id: storyboardId }),
    }),
  launchpad: (opts?: { q?: string; sort?: string; network?: string }) => {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.sort) params.set("sort", opts.sort);
    if (opts?.network) params.set("network", opts.network);
    const qs = params.toString();
    return request<any>(`/api/v1/veridiq/launchpad${qs ? `?${qs}` : ""}`);
  },
  launchpadChart: (coinId: string, days = 1) =>
    request<any>(`/api/v1/veridiq/launchpad/chart/${encodeURIComponent(coinId)}?days=${days}`),
  launchpadLaunch: (payload: {
    token_name: string;
    token_symbol: string;
    network?: string;
    initial_supply?: number;
    decimals?: number;
  }) =>
    request<any>("/api/v1/veridiq/launchpad/launch", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  osMonitor: (agentType?: string) =>
    request<any>(
      `/api/v1/veridiq/os/monitor${agentType ? `?agent_type=${encodeURIComponent(agentType)}` : ""}`
    ),
  sdkTools: () => request<any>("/api/v1/veridiq/sdk/tools"),
  sdkSendTask: (agentType: string, payload: { to_agent: string; task: any; execute?: boolean }) =>
    request<any>(`/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/sendTask`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  webrtcCreateRoom: (payload?: { label?: string; agent_type?: string }) =>
    request<any>("/api/v1/veridiq/webrtc/rooms", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  osMemory: (limit = 50) => request<any>(`/api/v1/veridiq/os/memory?limit=${limit}`),
  osCascade: (instruction: string) =>
    request<any>("/api/v1/veridiq/os/cascade", {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  platforms: () => request<any>("/api/v1/veridiq/platforms"),
  platformAction: (platform: string, action: string, args?: Record<string, unknown>, agentType?: string) =>
    request<any>(`/api/v1/veridiq/platforms/${encodeURIComponent(platform)}/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify({ args: args || {}, agent_type: agentType }),
    }),
  sdkReceiveTask: (agentType: string, limit = 10, claim = true) =>
    request<any>(
      `/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/receiveTask?limit=${limit}&claim=${claim}`
    ),
  sdkAskAgent: (agentType: string, payload: { to_agent: string; question: any }) =>
    request<any>(`/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/askAgent`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  sdkShareMemory: (agentType: string, payload: { key: string; value?: any; scope?: string; load_only?: boolean }) =>
    request<any>(`/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/shareMemory`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  sdkExecuteTool: (agentType: string, tool: string, args?: Record<string, unknown>) =>
    request<any>(`/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/executeTool`, {
      method: "POST",
      body: JSON.stringify({ tool, args: args || {} }),
    }),
  sdkProcessInbox: (agentType: string, limit = 5, execute = true) =>
    request<any>(
      `/api/v1/veridiq/sdk/${encodeURIComponent(agentType)}/processInbox?limit=${limit}&execute=${execute}`,
      { method: "POST" }
    ),
};

function notifySessionChange() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("veridiq-session"));
  }
}

export function saveSession(token: string, user: unknown) {
  localStorage.setItem("veridiq_token", token);
  localStorage.setItem("veridiq_user", JSON.stringify(user));
  notifySessionChange();
}

export function clearSession() {
  localStorage.removeItem("veridiq_token");
  localStorage.removeItem("veridiq_user");
  notifySessionChange();
}

/** True when a VERIDIQ API JWT is present (Clerk sync or legacy login). */
export function hasApiSession(): boolean {
  return Boolean(localStorage.getItem("veridiq_token"));
}
