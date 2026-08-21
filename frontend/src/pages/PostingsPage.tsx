import { type FormEvent, type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";

type ChatMsg = {
  role: "user" | "agent" | "system";
  text: string;
  meta?: any;
  image_url?: string | null;
  video_url?: string | null;
  audio_url?: string | null;
  message_id?: string;
};

type ChatSummary = {
  chat_id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

const LS_ACTIVE = "veridiq.postings.activeChatId";

const QUICK = [
  "Make a gym boy video",
  "Generate an image of a gym boy lifting weights at gym",
  "Make a cartoon video of agents introducing themselves at their desks",
  "Write a song about truth verification",
  "Create a post for VERIDIQ about truth verification",
];

/** Pull media URLs from action / meta / attachments / reply text. */
function extractMediaUrls(source: any): {
  image_url: string | null;
  video_url: string | null;
  audio_url: string | null;
} {
  if (!source || typeof source !== "object") {
    return { image_url: null, video_url: null, audio_url: null };
  }
  const render =
    source.render && typeof source.render === "object" ? source.render : {};
  const image =
    source.image && typeof source.image === "object" ? source.image : {};
  const song =
    source.song && typeof source.song === "object" ? source.song : {};
  const attachments = Array.isArray(source.attachments) ? source.attachments : [];
  const attachVideo = attachments
    .map((a: any) => (typeof a === "string" ? a : a?.video_url || a?.url || ""))
    .find((u: string) => /\.(mp4|webm|mov)(\?|$)/i.test(u) || /\/video\/file\//i.test(u));
  const attachImage = attachments
    .map((a: any) => (typeof a === "string" ? a : a?.image_url || a?.url || ""))
    .find((u: string) => /\.(jpg|jpeg|png|webp|gif)(\?|$)/i.test(u));
  const textBlob = String(source.text || source.message || source.reply || "");
  const textVideo =
    textBlob.match(/(\/api\/v1\/veridiq\/marketing\/video\/file\/[^\s"'<>]+\.(?:mp4|webm|mov))/i)?.[1] ||
    null;
  const video_url =
    source.video_url ||
    render.video_url ||
    source.meta?.video_url ||
    source.meta?.render?.video_url ||
    (source.action && typeof source.action === "object"
      ? source.action.video_url || source.action.render?.video_url
      : null) ||
    attachVideo ||
    textVideo ||
    null;
  const image_url =
    source.image_url ||
    image.image_url ||
    source.meta?.image_url ||
    (source.action && typeof source.action === "object"
      ? source.action.image_url || source.action.image?.image_url
      : null) ||
    attachImage ||
    null;
  const audio_url =
    source.audio_url ||
    song.audio_url ||
    render.audio_url ||
    source.meta?.audio_url ||
    (source.action && typeof source.action === "object"
      ? source.action.audio_url || source.action.song?.audio_url
      : null) ||
    null;
  return {
    image_url: image_url ? String(image_url) : null,
    video_url: video_url ? String(video_url) : null,
    audio_url: audio_url ? String(audio_url) : null,
  };
}

function mediaFromAction(action: any): {
  imageUrl?: string | null;
  videoUrl?: string | null;
  audioUrl?: string | null;
  lyrics?: string | null;
} {
  if (!action) return {};
  const urls = extractMediaUrls(action);
  const lyrics = action.lyrics || action.song?.lyrics || null;
  return {
    imageUrl: urls.image_url,
    videoUrl: urls.video_url,
    audioUrl: urls.audio_url,
    lyrics,
  };
}

/** Ensure render.video_url / top-level video_url stay in sync for StagePreview. */
function normalizeArtifact(action: any, urls?: ReturnType<typeof extractMediaUrls>): any | null {
  if (!action || typeof action !== "object") return null;
  const media = urls || extractMediaUrls(action);
  const next = { ...action };
  if (media.video_url) {
    next.video_url = media.video_url;
    const render =
      next.render && typeof next.render === "object" ? { ...next.render } : {};
    render.video_url = render.video_url || media.video_url;
    next.render = render;
    if (!next.action) next.action = "create_video";
  }
  if (media.image_url) {
    next.image_url = media.image_url;
    if (!next.action) next.action = "create_image";
  }
  if (media.audio_url) {
    next.audio_url = media.audio_url;
    if (!next.action) next.action = "create_song";
  }
  return next;
}

function isImageUrl(url: string): boolean {
  return /\.(jpg|jpeg|png|webp)(\?|$)/i.test(url);
}

function isGifUrl(url: string, format?: string): boolean {
  return String(format || "").toLowerCase() === "gif" || /\.gif(\?|$)/i.test(url);
}

/** Same-origin for Vite proxy — never leave absolute :8002 URLs in <video src>. */
function resolveMediaUrl(url: string): string {
  const raw = String(url || "").trim();
  if (!raw) return raw;
  const abs = raw.match(/^https?:\/\/(?:127\.0\.0\.1|localhost):8002(\/api\/[^\s?#]*)/i);
  if (abs) return abs[1] + (raw.includes("?") ? raw.slice(raw.indexOf("?")) : "");
  if (raw.startsWith("/api/")) return raw;
  return raw;
}

/** Convention: foo.mp4 → foo_poster.jpg next to the file (best-effort poster). */
function posterUrlFromVideo(src: string): string | undefined {
  const u = resolveMediaUrl(src);
  const m = u.match(/^(.*\/)([^/?#]+)\.(mp4|webm|mov)(\?[^#]*)?(#.*)?$/i);
  if (!m) return undefined;
  return `${m[1]}${m[2]}_poster.jpg${m[4] || ""}`;
}

function mapApiMessage(m: any): ChatMsg {
  const roleRaw = String(m?.role || "assistant");
  const role: ChatMsg["role"] =
    roleRaw === "user" ? "user" : roleRaw === "system" ? "system" : "agent";
  const meta = m?.meta && typeof m.meta === "object" ? m.meta : undefined;
  const fromMeta = extractMediaUrls({ ...(meta || {}), text: m?.text, ...m });
  return {
    role,
    text: String(m?.text || ""),
    meta,
    image_url: m?.image_url || fromMeta.image_url || null,
    video_url: m?.video_url || fromMeta.video_url || null,
    audio_url: m?.audio_url || fromMeta.audio_url || null,
    message_id: m?.message_id,
  };
}

function artifactFromMessages(msgs: ChatMsg[]): any | null {
  // Pass 1: newest message that actually has playable/viewable media
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    const urls = extractMediaUrls({
      ...(m.meta && typeof m.meta === "object" ? m.meta : {}),
      video_url: m.video_url,
      image_url: m.image_url,
      audio_url: m.audio_url,
      text: m.text,
    });
    if (!(urls.video_url || urls.image_url || urls.audio_url)) continue;

    if (m.meta && typeof m.meta === "object") {
      return normalizeArtifact({ ...m.meta, message: m.meta.message || m.text }, urls);
    }
    return normalizeArtifact(
      {
        action: urls.video_url ? "create_video" : urls.image_url ? "create_image" : "create_song",
        video_url: urls.video_url,
        image_url: urls.image_url,
        audio_url: urls.audio_url,
        render: urls.video_url ? { video_url: urls.video_url } : undefined,
        message: m.text,
      },
      urls,
    );
  }

  // Pass 2: newest non-started meta action (draft / help) — never steal stage from real media
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (!m.meta || typeof m.meta !== "object") continue;
    if (m.meta.status === "started") continue;
    if (!m.meta.action) continue;
    return normalizeArtifact({ ...m.meta, message: m.meta.message || m.text });
  }
  return null;
}

/** Prefer artifact with real media; fall back to scanning messages. */
function resolveStageArtifact(artifact: any, msgs: ChatMsg[]): any | null {
  const fromMsgs = artifactFromMessages(msgs);
  const aMedia = mediaFromAction(artifact);
  const mMedia = mediaFromAction(fromMsgs);
  if (aMedia.videoUrl || aMedia.imageUrl || aMedia.audioUrl) {
    return normalizeArtifact(artifact);
  }
  if (mMedia.videoUrl || mMedia.imageUrl || mMedia.audioUrl) {
    return fromMsgs;
  }
  return normalizeArtifact(artifact) || fromMsgs;
}

function greetingMessage(persona: any): ChatMsg {
  return {
    role: "agent",
    text:
      persona?.greeting ||
      "Hi — I'm Mira. Ask me for an image, cartoon video, song, or social draft — one command.",
  };
}

export default function PostingsPage() {
  const [persona, setPersona] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyHint, setBusyHint] = useState("Generating…");
  const [busyElapsed, setBusyElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [artifact, setArtifact] = useState<any>(null);
  const [pendingUploads, setPendingUploads] = useState<
    Array<{ filename: string; url: string; previewUrl: string; name: string }>
  >([]);
  const [uploading, setUploading] = useState(false);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [chatsLoading, setChatsLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [learningRated, setLearningRated] = useState<number | null>(null);
  const [feedbackSent, setFeedbackSent] = useState<"up" | "down" | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busyStartedRef = useRef<number | null>(null);
  const activeChatRef = useRef<string | null>(null);

  useEffect(() => {
    activeChatRef.current = activeChatId;
    if (activeChatId) {
      try {
        localStorage.setItem(LS_ACTIVE, activeChatId);
      } catch {
        /* ignore */
      }
    }
  }, [activeChatId]);

  const refreshChatList = useCallback(async () => {
    try {
      const data = await api.postingsChats();
      setChats((data.chats || []) as ChatSummary[]);
    } catch {
      /* keep existing list */
    }
  }, []);

  const loadChat = useCallback(
    async (chatId: string, personaData?: any) => {
      const data = await api.postingsChatGet(chatId);
      const mapped = (data.messages || []).map(mapApiMessage);
      const withGreeting =
        mapped.length === 0 ? [greetingMessage(personaData || persona)] : mapped;
      setMessages(withGreeting);
      const nextArtifact = artifactFromMessages(mapped);
      setArtifact(nextArtifact);
      const stageVideoUrl =
        nextArtifact?.render?.video_url || nextArtifact?.video_url || null;
      const msgVideo =
        [...mapped]
          .reverse()
          .map((m) => m.video_url || extractMediaUrls(m.meta || {}).video_url)
          .find(Boolean) || null;
      if (!stageVideoUrl) {
        console.warn("[Postings] stageVideoUrl missing on chat open", {
          chatId,
          msgVideo,
          action: nextArtifact?.action,
          messageCount: mapped.length,
        });
        // Last resort: if a message has video_url but artifact missed it, force stage
        if (msgVideo) {
          setArtifact(
            normalizeArtifact({
              action: "create_video",
              video_url: msgVideo,
              render: { video_url: msgVideo },
              message: "Video ready.",
            }),
          );
        }
      } else {
        console.info("[Postings] stageVideoUrl restored", stageVideoUrl);
      }
      setActiveChatId(chatId);
      setError(null);
    },
    [persona],
  );

  const startNewChat = useCallback(
    async (personaData?: any) => {
      const created = await api.postingsChatCreate("");
      const id = String(created.chat_id);
      setActiveChatId(id);
      setMessages([greetingMessage(personaData || persona)]);
      setArtifact(null);
      setError(null);
      await refreshChatList();
      return id;
    },
    [persona, refreshChatList],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setChatsLoading(true);
        const [agentData, listData, learnData] = await Promise.all([
          api.postingsAgent(),
          api.postingsChats().catch(() => ({ chats: [] })),
          api.postingsFeedbackStats().catch(() => null),
        ]);
        if (cancelled) return;
        setPersona(agentData.agent);
        setStatus(agentData);
        if (learnData && typeof learnData.rated_examples === "number") {
          setLearningRated(learnData.rated_examples);
        } else if (agentData?.learning?.rated_examples != null) {
          setLearningRated(Number(agentData.learning.rated_examples));
        }
        const list = (listData.chats || []) as ChatSummary[];
        setChats(list);

        let stored: string | null = null;
        try {
          stored = localStorage.getItem(LS_ACTIVE);
        } catch {
          stored = null;
        }

        if (stored && list.some((c) => c.chat_id === stored)) {
          await loadChat(stored, agentData.agent);
        } else if (list.length > 0) {
          await loadChat(list[0].chat_id, agentData.agent);
        } else {
          await startNewChat(agentData.agent);
        }
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Could not load Postings Studio");
      } finally {
        if (!cancelled) setChatsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot once
  }, []);

  useEffect(() => {
    setFeedbackSent(null);
  }, [artifact?.image_url, artifact?.video_url, artifact?.render?.video_url, artifact?.action]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, busyHint]);

  useEffect(() => {
    if (!busy) {
      setBusyElapsed(0);
      busyStartedRef.current = null;
      return;
    }
    busyStartedRef.current = Date.now();
    const tick = window.setInterval(() => {
      const started = busyStartedRef.current;
      if (!started) return;
      const secs = Math.floor((Date.now() - started) / 1000);
      setBusyElapsed(secs);
      if (secs >= 150) {
        setBusyHint((prev) =>
          prev.includes("still working")
            ? prev
            : `${prev.replace(/\s*·\s*elapsed.*$/i, "")} · still working (${secs}s) — you can retry`,
        );
      }
    }, 1000);
    return () => window.clearInterval(tick);
  }, [busy]);

  async function ensureChatId(): Promise<string> {
    if (activeChatRef.current) return activeChatRef.current;
    const id = await startNewChat();
    return id;
  }

  async function send(text: string) {
    const msg = text.trim();
    const attachFilenames = pendingUploads.map((u) => u.filename);
    if ((!msg && attachFilenames.length === 0) || busy) return;
    const sendText = msg || (attachFilenames.length ? "Use my uploaded image" : "");
    const low = sendText.toLowerCase();
    let isVideo = false;
    if (/\b(video|vidoe|vedio|reel|mp4|gif|clip|storyboard)\b/.test(low)) {
      isVideo = true;
      const minMatch = low.match(
        /\b(?:about|around|~)?\s*(\d+(?:\.\d+)?)\s*(?:minutes?|minuts?|mints?|mins?|mint|min|m)\b/,
      );
      const secMatch = low.match(/\b(?:about|around|~)?\s*(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b/);
      let scenes = 3;
      let playback = "~15s";
      let longForm = false;
      if (minMatch) {
        const m = Number(minMatch[1]);
        const secs = Math.round(m * 60);
        playback = m >= 1 ? `${m}:00` : `~${secs}s`;
        longForm = secs >= 60;
        scenes = 3;
      } else if (secMatch) {
        const secs = Math.round(Number(secMatch[1]));
        playback = `~${secs}s`;
        longForm = secs >= 60;
        scenes = 3;
      }
      const eta = "~50–70s";
      const fpsNote = longForm ? "1080p · 15fps" : "1080p · 30fps";
      setBusyHint(
        attachFilenames.length
          ? `Video from ${attachFilenames.length} upload(s)… · ${playback} · ${fpsNote} (ETA ${eta})`
          : `Generating ${scenes} scenes… · ${playback} · ${fpsNote} (ETA ${eta})`,
      );
    } else if (
      /\b(imae|imag|imge|images?|pics?|pictures?|photos?|draw|illustration|visual|va\s+ima)/.test(low) ||
      /\bnot\s+as\s+text\b/.test(low) ||
      attachFilenames.length > 0
    ) {
      setBusyHint(attachFilenames.length ? "Using uploaded image…" : "Generating image…");
    } else if (/\b(songs?|music|lyrics|melody|track)\b/.test(low)) {
      setBusyHint("Writing song + music…");
    } else {
      setBusyHint("Generating…");
    }
    setBusy(true);
    setError(null);
    setInput("");
    setArtifact(null);
    const userLabel =
      attachFilenames.length > 0
        ? `${sendText}${msg ? "" : ""} · ${attachFilenames.length} image(s)`
        : sendText;
    setMessages((prev) => [...prev, { role: "user", text: userLabel }]);
    setPendingUploads((prev) => {
      for (const u of prev) {
        if (u.previewUrl.startsWith("blob:")) URL.revokeObjectURL(u.previewUrl);
      }
      return [];
    });
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const softTimer = window.setTimeout(() => {
      if (!ac.signal.aborted) {
        setBusyHint((prev) =>
          prev.includes("taking longer")
            ? prev
            : `${prev} · taking longer than expected — wait or retry`,
        );
      }
    }, isVideo ? 70_000 : 45_000);
    const hardTimer = isVideo
      ? null
      : window.setTimeout(() => {
          ac.abort();
        }, 75_000);
    const postAbort = isVideo
      ? (() => {
          const postAc = new AbortController();
          const t = window.setTimeout(() => postAc.abort(), 25_000);
          return { postAc, t };
        })()
      : null;
    try {
      const chatId = await ensureChatId();
      const history = messages
        .filter((m) => m.role === "user" || m.role === "agent")
        .slice(-8)
        .map((m) => {
          const base: { role: string; text: string; audio_url?: string; audio_path?: string } = {
            role: m.role === "agent" ? "assistant" : "user",
            text: m.text,
          };
          const audio = m.meta?.audio_url || m.meta?.song?.audio_url || m.audio_url || m.meta?.audio_path;
          if (audio) base.audio_url = String(audio);
          return base;
        });
      const res = await api.postingsAgentCommand(
        sendText,
        history,
        {
          signal: postAbort ? postAbort.postAc.signal : ac.signal,
        },
        attachFilenames,
        chatId,
      );
      if (postAbort) window.clearTimeout(postAbort.t);
      if (res.chat_title) {
        setChats((prev) =>
          prev.map((c) => (c.chat_id === chatId ? { ...c, title: res.chat_title } : c)),
        );
      }
      void refreshChatList();

      const jobId = res.job_id || res.action?.job_id;
      const started =
        Boolean(jobId) &&
        (res.status === "started" || res.action?.status === "started" || res.intent === "create_video");

      if (started && jobId) {
        setBusyHint(res.reply || res.action?.message || "Video job started — rendering…");
        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            text: res.reply || "Rendering video in the background…",
            meta: { ...(res.action || {}), job_id: jobId, status: "started" },
          },
        ]);

        const pollMaxMs = 180_000;
        const pollExtraMs = 60_000;
        const pollStarted = Date.now();
        let warnedExtra = false;
        let finalJob: any = null;

        while (true) {
          if (ac.signal.aborted) throw new DOMException("Aborted", "AbortError");
          await new Promise((r) => setTimeout(r, 2_000));
          const elapsed = Date.now() - pollStarted;
          if (elapsed > pollMaxMs && !warnedExtra) {
            warnedExtra = true;
            const keepMsg =
              "Still rendering — keep waiting a bit longer (server is finishing the MP4).";
            setBusyHint(keepMsg);
            setError(null);
            setMessages((prev) => [...prev, { role: "system", text: keepMsg }]);
          }
          if (elapsed > pollMaxMs + pollExtraMs) {
            throw new Error(
              "Video is still rendering after ~4 min. Check back shortly or retry — the server may still finish.",
            );
          }
          const job = await api.postingsVideoJob(String(jobId), { signal: ac.signal });
          finalJob = job;
          const prog = typeof job.progress === "number" ? job.progress : null;
          const jmsg = String(job.message || "").trim();
          if (jmsg) {
            setBusyHint(prog != null ? `${jmsg} (${prog}%)` : jmsg);
          }
          if (job.status === "done" || job.status === "error") break;
        }

        if (!finalJob || finalJob.status === "error") {
          const errText = finalJob?.message || finalJob?.reply || "Video generation failed.";
          setError(errText);
          setMessages((prev) => [...prev, { role: "system", text: errText }]);
          return;
        }

        const done = finalJob.result || finalJob;
        const rawAction =
          (done.action && typeof done.action === "object" ? done.action : null) ||
          (finalJob.action && typeof finalJob.action === "object" ? finalJob.action : null) ||
          (typeof done === "object" ? done : null);
        const media = mediaFromAction(rawAction);
        // Also dig job.result / top-level fields if action nesting is odd
        const fallbackUrls = extractMediaUrls({
          ...(rawAction || {}),
          ...(typeof done === "object" ? done : {}),
          video_url:
            media.videoUrl ||
            finalJob.video_url ||
            done?.video_url ||
            done?.render?.video_url,
        });
        const action = normalizeArtifact(rawAction || { action: "create_video" }, fallbackUrls);
        const reply =
          done.reply || action?.message || finalJob.message || "Video ready.";
        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            text: reply,
            meta: action,
            video_url: fallbackUrls.video_url || media.videoUrl,
            image_url: fallbackUrls.image_url || media.imageUrl,
            audio_url: fallbackUrls.audio_url || media.audioUrl,
          },
        ]);
        if (action) setArtifact(action);
        console.info("[Postings] video job done — stage set", {
          video_url: action?.video_url || action?.render?.video_url,
        });
        void refreshChatList();
        return;
      }

      const reply = res.reply || res.action?.message || "Done.";
      const media = mediaFromAction(res.action);
      const action = res.action ? normalizeArtifact(res.action) : null;
      setMessages((prev) => [
        ...prev,
        {
          role: "agent",
          text: reply,
          meta: action || res.action,
          video_url: media.videoUrl,
          image_url: media.imageUrl,
          audio_url: media.audioUrl,
        },
      ]);
      if (action) setArtifact(action);
      void refreshChatList();
    } catch (err: any) {
      const aborted = err?.name === "AbortError" || /aborted|abort/i.test(String(err?.message || ""));
      const msgText = aborted
        ? isVideo
          ? "Could not start video job — server may be down. Retry in a few seconds."
          : "Image/request timed out. Wait a few seconds and retry."
        : err.message || "Request failed";
      setError(msgText);
      setMessages((prev) => [...prev, { role: "system", text: msgText }]);
    } finally {
      window.clearTimeout(softTimer);
      if (hardTimer != null) window.clearTimeout(hardTimer);
      if (postAbort) window.clearTimeout(postAbort.t);
      setBusy(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  async function uploadImageFiles(files: File[]) {
    const images = files.filter(
      (f) => /^image\//i.test(f.type) || /\.(png|jpe?g|webp|gif)$/i.test(f.name),
    );
    if (!images.length) {
      setError("Only image files are supported (png, jpg, webp, gif).");
      return;
    }
    if (busy || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const out = await api.postingsUpload(images.slice(0, 8));
      const uploads = out.uploads || [];
      setPendingUploads((prev) => {
        const next = [...prev];
        for (let i = 0; i < uploads.length; i++) {
          const u = uploads[i];
          const local = images[i];
          next.push({
            filename: u.filename,
            url: u.url,
            previewUrl: local ? URL.createObjectURL(local) : u.url,
            name: local?.name || u.filename,
          });
        }
        return next.slice(0, 8);
      });
    } catch (err: any) {
      setError(err?.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onPickFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    await uploadImageFiles(Array.from(fileList));
  }

  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      if (busy || uploading) return;
      const items = e.clipboardData?.items;
      if (!items?.length) return;
      const files: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (!item || !/^image\//i.test(item.type)) continue;
        const blob = item.getAsFile();
        if (!blob) continue;
        const ext = (item.type.split("/")[1] || "png").replace("jpeg", "jpg");
        const named =
          blob.name && blob.name !== "image.png"
            ? blob
            : new File([blob], `clipboard-${Date.now()}-${i}.${ext}`, {
                type: blob.type || "image/png",
              });
        files.push(named);
      }
      if (!files.length) return;
      e.preventDefault();
      void uploadImageFiles(files);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [busy, uploading]);

  function removePending(filename: string) {
    setPendingUploads((prev) => {
      const doomed = prev.find((u) => u.filename === filename);
      if (doomed?.previewUrl.startsWith("blob:")) URL.revokeObjectURL(doomed.previewUrl);
      return prev.filter((u) => u.filename !== filename);
    });
  }

  async function onSelectChat(chatId: string) {
    if (busy || chatId === activeChatId) return;
    abortRef.current?.abort();
    try {
      await loadChat(chatId);
    } catch (err: any) {
      setError(err?.message || "Could not open chat");
    }
  }

  async function onNewChat() {
    if (busy) return;
    abortRef.current?.abort();
    try {
      await startNewChat();
    } catch (err: any) {
      setError(err?.message || "Could not create chat");
    }
  }

  async function onDeleteChat(chatId: string, e: MouseEvent) {
    e.stopPropagation();
    if (busy) return;
    try {
      await api.postingsChatDelete(chatId);
      const next = chats.filter((c) => c.chat_id !== chatId);
      setChats(next);
      if (activeChatId === chatId) {
        if (next.length) await loadChat(next[0].chat_id);
        else await startNewChat();
      }
    } catch (err: any) {
      setError(err?.message || "Could not delete chat");
    }
  }

  const name = persona?.name || "Mira";
  const geminiOk = status?.gemini?.configured;
  const llmOk = status?.llm?.configured;
  const videoOk = status?.video_render?.configured;
  const miraTier = status?.tier || "free";
  const stageArtifact = resolveStageArtifact(artifact, messages);
  const stageMedia = mediaFromAction(stageArtifact);
  const canSend = Boolean(input.trim() || pendingUploads.length) && !busy && !uploading;

  return (
    <AppShell title="Postings" subtitle="Mira studio — persistent chats, images, videos, songs">
      {error ? <div className="banner error">{error}</div> : null}

      <div className={`mira-studio ${sidebarOpen ? "mira-sidebar-open" : "mira-sidebar-collapsed"}`}>
        <aside className="mira-chats panel glass" aria-label="Chat history">
          <div className="mira-chats-head">
            <button type="button" className="btn btn-primary mira-new-chat" onClick={() => void onNewChat()} disabled={busy}>
              New chat
            </button>
            <button
              type="button"
              className="btn btn-ghost mira-sidebar-toggle"
              aria-label={sidebarOpen ? "Collapse chats" : "Expand chats"}
              onClick={() => setSidebarOpen((v) => !v)}
            >
              {sidebarOpen ? "‹" : "›"}
            </button>
          </div>
          <div className="mira-chats-list" role="list">
            {chatsLoading ? (
              <p className="muted mira-chats-empty">Loading chats…</p>
            ) : chats.length === 0 ? (
              <p className="muted mira-chats-empty">No chats yet</p>
            ) : (
              chats.map((c) => (
                <button
                  key={c.chat_id}
                  type="button"
                  role="listitem"
                  className={`mira-chat-item ${c.chat_id === activeChatId ? "active" : ""}`}
                  onClick={() => void onSelectChat(c.chat_id)}
                  disabled={busy}
                  title={c.title}
                >
                  <span className="mira-chat-title">{c.title || "New chat"}</span>
                  <span
                    className="mira-chat-delete"
                    role="button"
                    tabIndex={0}
                    aria-label="Delete chat"
                    onClick={(e) => void onDeleteChat(c.chat_id, e)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        void onDeleteChat(c.chat_id, e as any);
                      }
                    }}
                  >
                    ×
                  </span>
                </button>
              ))
            )}
          </div>
        </aside>

        <section className="mira-main panel glass">
          <header className="mira-main-head">
            <div>
              <p className="mira-eyebrow">Postings Studio</p>
              <h2 className="mira-agent-name">{name}</h2>
              <p className="muted mira-agent-sub">{persona?.specialty || "Creative postings agent"}</p>
            </div>
            <div className="postings-status-pills" aria-label="Integration status">
              <span className="postings-pill ok">Mira Free</span>
              <span className={`postings-pill ${miraTier === "free" ? "ok" : "warn"}`}>
                {miraTier === "premium" ? "Premium" : "Free tier"}
              </span>
              <span className={`postings-pill ${geminiOk ? "ok" : "warn"}`}>
                Gemini {geminiOk ? "on" : "off"}
              </span>
              <span className={`postings-pill ${llmOk ? "ok" : "warn"}`}>
                LLM {llmOk ? "on" : "off"}
              </span>
              <span className={`postings-pill ${videoOk ? "ok" : "warn"}`}>
                Video {videoOk ? "ready" : "storyboard"}
              </span>
              <span className="postings-pill ok" title="Learns from your ratings & uploads — free, no Unsplash/Meta">
                Learning: {learningRated ?? status?.learning?.rated_examples ?? 0} rated
              </span>
            </div>
          </header>

          <div className="mira-stage" aria-live="polite">
            {busy && !stageMedia.videoUrl && !stageMedia.imageUrl ? (
              <div className="postings-stage-empty">
                <p className="postings-stage-hint">
                  {name} is {busyHint}
                  {busyElapsed > 0 ? ` · elapsed ${busyElapsed}s` : ""}
                </p>
              </div>
            ) : stageMedia.videoUrl || stageMedia.imageUrl || stageArtifact ? (
              <StagePreview
                action={
                  stageArtifact || {
                    action: stageMedia.videoUrl ? "create_video" : "create_image",
                    video_url: stageMedia.videoUrl,
                    image_url: stageMedia.imageUrl,
                    render: stageMedia.videoUrl
                      ? { video_url: stageMedia.videoUrl }
                      : undefined,
                  }
                }
                chatId={activeChatId}
                feedbackSent={feedbackSent}
                onFeedback={async (thumbs) => {
                  const media = mediaFromAction(stageArtifact || artifact);
                  const mediaUrl = media.videoUrl || media.imageUrl || "";
                  const mediaType = media.videoUrl ? "video" : "image";
                  try {
                    await api.postingsFeedback({
                      thumbs,
                      media_url: mediaUrl,
                      media_type: mediaType,
                      chat_id: activeChatId || "",
                      prompt: String(
                        stageArtifact?.message ||
                          stageArtifact?.storyboard?.title ||
                          artifact?.message ||
                          "",
                      ),
                      style: String(stageArtifact?.style || artifact?.style || ""),
                      topic: String(
                        stageArtifact?.storyboard?.title ||
                          stageArtifact?.topic ||
                          stageArtifact?.message ||
                          "",
                      ),
                    });
                    setFeedbackSent(thumbs);
                    setLearningRated((n) => (n == null ? 1 : n + 1));
                  } catch (err: any) {
                    setError(err?.message || "Could not save rating");
                  }
                }}
              />
            ) : (
              <div className="postings-stage-empty">
                <p className="postings-stage-hint">
                  Artifacts land here. Chats persist — leave and come back anytime.
                </p>
              </div>
            )}
          </div>

          <div className="mira-messages" role="log">
            {messages.map((m, i) => (
              <div
                key={m.message_id || i}
                className={`mira-bubble ${m.role === "user" ? "user" : m.role === "system" ? "system" : "agent"}`}
              >
                <p>{m.text}</p>
                {(m.video_url ||
                  m.image_url ||
                  m.audio_url ||
                  extractMediaUrls(m.meta || {}).video_url) && (
                  <div className="mira-bubble-media">
                    {(() => {
                      const vu =
                        m.video_url || extractMediaUrls(m.meta || {}).video_url;
                      const iu =
                        m.image_url || extractMediaUrls(m.meta || {}).image_url;
                      const au =
                        m.audio_url || extractMediaUrls(m.meta || {}).audio_url;
                      return (
                        <>
                          {vu && !(isGifUrl(vu) || isImageUrl(vu)) && (
                            <MiraVideo src={vu} className="mira-bubble-video" />
                          )}
                          {(iu || (vu && (isGifUrl(vu) || isImageUrl(vu)))) && (
                            <img src={(iu || vu)!} alt="" />
                          )}
                          {au ? <audio src={au} controls /> : null}
                        </>
                      );
                    })()}
                  </div>
                )}
              </div>
            ))}
            {busy ? (
              <div className="mira-bubble agent">
                <p className="muted">
                  {name} is {busyHint}
                  {busyElapsed > 0 ? ` · elapsed ${busyElapsed}s` : ""}
                </p>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>

          <div className="mira-dock">
            {pendingUploads.length > 0 ? (
              <div className="postings-attach-previews" aria-label="Pending uploads">
                {pendingUploads.map((u) => (
                  <div key={u.filename} className="postings-attach-thumb">
                    <img src={u.previewUrl} alt={u.name} />
                    <button
                      type="button"
                      className="postings-attach-remove"
                      aria-label={`Remove ${u.name}`}
                      onClick={() => removePending(u.filename)}
                      disabled={busy}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            <form className="mira-compose" onSubmit={onSubmit}>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif"
                multiple
                hidden
                onChange={(e) => void onPickFiles(e.target.files)}
              />
              <button
                type="button"
                className="btn btn-ghost postings-attach-btn"
                title="Upload images"
                aria-label="Upload images"
                disabled={busy || uploading}
                onClick={() => fileRef.current?.click()}
              >
                {uploading ? "…" : "Attach"}
              </button>
              <input
                ref={inputRef}
                className="field mira-input"
                placeholder={`Message ${name}…`}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={busy}
                autoComplete="off"
              />
              <button className="btn btn-primary" type="submit" disabled={!canSend}>
                Send
              </button>
            </form>

            <div className="postings-quick mira-quick">
              {QUICK.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => void send(q)}
                >
                  {q}
                </button>
              ))}
            </div>

            {stageArtifact ? (
              <div className="mira-dock-meta">
                <ArtifactMeta action={stageArtifact} />
              </div>
            ) : null}

            <p className="muted mira-foot">
              Learns from your ratings &amp; uploads — free, no Unsplash/Meta
              {learningRated != null ? ` (${learningRated} rated)` : ""}. Nothing posts
              live until you approve in{" "}
              <Link className="text-link" to="/dashboard/comms">
                Comms
              </Link>{" "}
              or{" "}
              <Link className="text-link" to="/dashboard/marketing">
                Marketing
              </Link>
              .
            </p>
          </div>
        </section>
      </div>
    </AppShell>
  );
}

/** Stage/chat video — same-origin URL, muted autoplay + seek paint, poster, visible errors. */
function MiraVideo({
  src,
  className,
  poster,
}: {
  src: string;
  className?: string;
  poster?: string | null;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const resolved = resolveMediaUrl(src);
  const posterSrc = poster ? resolveMediaUrl(poster) : posterUrlFromVideo(resolved);
  const [errInfo, setErrInfo] = useState<string | null>(null);

  useEffect(() => {
    setErrInfo(null);
    const el = ref.current;
    if (!el || !resolved) return;
    el.muted = true;
    el.defaultMuted = true;
    el.setAttribute("muted", "");
    el.playsInline = true;

    const forcePaint = () => {
      try {
        if (el.currentTime < 0.05) el.currentTime = 0.1;
      } catch {
        /* ignore seek before metadata */
      }
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => undefined);
    };

    const onReady = () => forcePaint();
    el.addEventListener("loadeddata", onReady);
    el.addEventListener("canplay", onReady);
    if (el.readyState >= 2) forcePaint();

    return () => {
      el.removeEventListener("loadeddata", onReady);
      el.removeEventListener("canplay", onReady);
    };
  }, [resolved]);

  async function onVideoError() {
    const el = ref.current;
    let status = "?";
    try {
      const res = await fetch(resolved, { method: "HEAD" });
      status = String(res.status);
    } catch (e: any) {
      status = `fetch-failed (${e?.message || "network"})`;
    }
    const mediaErr = el?.error;
    const code = mediaErr ? ` media.code=${mediaErr.code}` : "";
    setErrInfo(`Video failed · HTTP ${status}${code} · src=${resolved}`);
    console.error("[Postings] MiraVideo error", { src: resolved, status, mediaErr });
  }

  if (!resolved) {
    return (
      <div className="mira-video-error" role="alert">
        Video src is empty — artifact.video_url / render.video_url missing.
      </div>
    );
  }

  return (
    <div className="mira-video-shell">
      <video
        ref={ref}
        key={resolved}
        className={className}
        src={resolved}
        poster={posterSrc}
        controls
        autoPlay
        muted
        playsInline
        preload="metadata"
        onError={() => void onVideoError()}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          display: "block",
        }}
      />
      {errInfo ? (
        <div className="mira-video-error" role="alert">
          {errInfo}
        </div>
      ) : null}
    </div>
  );
}

function FeedbackBar({
  sent,
  onFeedback,
}: {
  sent: "up" | "down" | null;
  onFeedback?: (thumbs: "up" | "down") => void | Promise<void>;
}) {
  if (!onFeedback) return null;
  return (
    <div className="mira-feedback-bar" role="group" aria-label="Rate this output">
      <span className="muted mira-feedback-label">Rate for Mira learning</span>
      <button
        type="button"
        className={`btn btn-ghost btn-sm mira-feedback-btn${sent === "up" ? " active" : ""}`}
        disabled={!!sent}
        aria-label="Thumbs up"
        onClick={() => void onFeedback("up")}
      >
        👍
      </button>
      <button
        type="button"
        className={`btn btn-ghost btn-sm mira-feedback-btn${sent === "down" ? " active" : ""}`}
        disabled={!!sent}
        aria-label="Thumbs down"
        onClick={() => void onFeedback("down")}
      >
        👎
      </button>
      {sent ? <span className="muted mira-feedback-thanks">Saved</span> : null}
    </div>
  );
}

function StagePreview({
  action,
  chatId: _chatId,
  feedbackSent,
  onFeedback,
}: {
  action: any;
  chatId?: string | null;
  feedbackSent?: "up" | "down" | null;
  onFeedback?: (thumbs: "up" | "down") => void | Promise<void>;
}) {
  const { imageUrl, videoUrl, audioUrl, lyrics } = mediaFromAction(action);
  const format = action?.render?.format;
  const bar = (
    <FeedbackBar sent={feedbackSent ?? null} onFeedback={onFeedback} />
  );

  // Always mount the player when a video URL exists — don't require action===create_video
  if (videoUrl && !(isGifUrl(videoUrl, format) || isImageUrl(videoUrl))) {
    return (
      <div className="postings-stage-media">
        <MiraVideo
          src={videoUrl}
          className="postings-stage-video"
          poster={action?.render?.poster_url || action?.poster_url || null}
        />
        {audioUrl ? <audio src={resolveMediaUrl(audioUrl)} controls className="postings-stage-audio" /> : null}
        {bar}
      </div>
    );
  }

  if (videoUrl && (isGifUrl(videoUrl, format) || isImageUrl(videoUrl))) {
    return (
      <div className="postings-stage-media">
        <img src={resolveMediaUrl(videoUrl)} alt="Generated video" />
        {bar}
      </div>
    );
  }

  if ((action.action === "create_image" || action.action === "create_design" || imageUrl) && imageUrl) {
    return (
      <div className="postings-stage-media">
        <img src={imageUrl} alt="Generated" />
        {bar}
      </div>
    );
  }

  if (action.action === "create_song") {
    return (
      <div className="postings-stage-media postings-stage-song">
        {lyrics ? <pre className="draft-body postings-lyrics">{lyrics}</pre> : null}
        {audioUrl ? <audio controls src={audioUrl} className="postings-stage-audio" /> : null}
      </div>
    );
  }

  if (action.action === "draft_post" && action.draft) {
    return (
      <div className="postings-stage-media postings-stage-draft">
        <h4>{action.draft.subject || "Queued draft"}</h4>
        <pre className="draft-body">{action.draft.body}</pre>
      </div>
    );
  }

  return (
    <div className="postings-stage-empty">
      <p className="postings-stage-hint">
        {action.action === "create_video" && !videoUrl
          ? "Video metadata is ready, but the file URL is missing — re-open this chat or regenerate."
          : action.message || "Ready."}
      </p>
    </div>
  );
}

function ArtifactMeta({ action }: { action: any }) {
  if (action.action === "create_video") {
    const board = action.storyboard || {};
    const render = action.render || {};
    const videoHref = render.video_url || action.video_url || null;
    const durLabel =
      action.duration_label ||
      render.duration_label ||
      (action.duration_sec ? `${action.duration_sec}s` : null) ||
      (board.duration_sec ? `${board.duration_sec}s` : null);
    return (
      <>
        <p className="muted">
          Video{action.style ? ` · ${action.style}` : ""}
          {durLabel ? ` · ${durLabel}` : ""}
          {action.stills_count != null ? ` · ${action.stills_count} stills` : ""}
          {` · ${action.quality?.label || "1080p · 30fps"}`}
        </p>
        <h4>{board.title || "Storyboard"}</h4>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          {action.message || render.message}
        </p>
        {videoHref ? (
          <a className="btn btn-primary btn-sm" href={videoHref} target="_blank" rel="noreferrer">
            Open file
          </a>
        ) : null}
      </>
    );
  }
  if (action.action === "create_image" || action.action === "create_design") {
    const imgUrl = action.image_url || action.image?.image_url;
    return (
      <>
        <p className="muted">
          {action.action === "create_design" ? "Design" : "Image"}
          {action.provider ? ` · ${action.provider}` : ""}
        </p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          {action.message}
        </p>
        {imgUrl ? (
          <a className="btn btn-primary btn-sm" href={imgUrl} target="_blank" rel="noreferrer">
            Open image
          </a>
        ) : null}
      </>
    );
  }
  if (action.action === "create_song") {
    const audioUrl = action.audio_url || action.song?.audio_url;
    return (
      <>
        <p className="muted">Song{action.provider ? ` · ${action.provider}` : ""}</p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          {action.message}
        </p>
        {audioUrl ? (
          <a className="btn btn-primary btn-sm" href={audioUrl} target="_blank" rel="noreferrer">
            Open audio
          </a>
        ) : null}
      </>
    );
  }
  if (action.action === "draft_post" && action.draft) {
    return (
      <>
        <p className="muted">Draft · {action.channel || "post"}</p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          {action.message}
        </p>
        <Link className="btn btn-ghost btn-sm" to="/dashboard/comms">
          Open Comms to approve
        </Link>
      </>
    );
  }
  return (
    <p className="muted" style={{ fontSize: "0.85rem" }}>
      {action.message || action.action || "result"}
    </p>
  );
}
