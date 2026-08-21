import { useEffect, useRef, useState } from "react";
import {
  LocalAudioTrack,
  LocalVideoTrack,
  Room,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  type LocalTrackPublication,
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  type TrackPublication,
} from "livekit-client";
import { AgentAvatar } from "./AppShell";

export type MeetingParticipant = {
  agent_type?: string;
  name: string;
  role?: string;
  avatar_hue?: number;
  avatar_presentation?: string;
  avatar_hair?: string;
  avatar_skin?: string;
  avatar_hair_color?: string;
  kind?: string;
};

export type AgentPresencePayload = {
  token?: string;
  url?: string;
  identity?: string;
  name?: string;
  audioUrl?: string | null;
  greetingScript?: string | null;
  agent?: MeetingParticipant | null;
  agentType?: string;
  maxCallSeconds?: number;
  timedSessionId?: string | null;
};

export type DialogueTurn = {
  agent_type?: string;
  name?: string;
  text?: string;
  audioUrl?: string | null;
};

type Props = {
  token: string;
  url: string;
  agents: MeetingParticipant[];
  /** When set, connects a second LiveKit participant (Marcus) and publishes TTS audio. */
  agentPresence?: AgentPresencePayload | null;
  /** Multi-agent presence (agent↔agent meetings). */
  multiAgentPresence?: AgentPresencePayload[] | null;
  /** Turn-taking TTS dialogue between agents. */
  dialogue?: DialogueTurn[] | null;
  /** Spectator: subscribe-only; mic/cam muted by default. */
  spectatorMode?: boolean;
  onDisconnect?: () => void;
  onError?: (message: string) => void;
  onAgentSpeakingChange?: (speaking: boolean) => void;
  /** Fired once when Marcus has joined (start timed budget). */
  onAgentJoined?: (info: { timedSessionId?: string | null }) => void;
  /** Fired when agent join fails (cancel uncharged timed session). */
  onAgentJoinFailed?: (info: { timedSessionId?: string | null; message: string }) => void;
};

type Tile = {
  id: string;
  label: string;
  kind: "local" | "remote" | "agent" | "screen";
  hue?: number;
  presentation?: string;
  hair?: string;
  skin?: string;
  hairColor?: string;
  stream?: MediaStream;
  speaking?: boolean;
};

function attachTrack(el: HTMLVideoElement | null, stream?: MediaStream) {
  if (!el) return;
  if (stream) {
    el.srcObject = stream;
    void el.play().catch(() => undefined);
  } else {
    el.srcObject = null;
  }
}

function VideoTile({ tile }: { tile: Tile }) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    attachTrack(ref.current, tile.stream);
  }, [tile.stream]);

  return (
    <div className={`lk-tile ${tile.kind}${tile.speaking ? " is-speaking" : ""}`}>
      {tile.stream ? (
        <video
          ref={ref}
          className="lk-video"
          autoPlay
          playsInline
          muted={tile.kind === "local" || tile.kind === "screen"}
        />
      ) : (
        <div className="lk-avatar-fallback">
          <AgentAvatar
            name={tile.label}
            hue={tile.hue ?? 210}
            size={72}
            presentation={tile.presentation}
            hair={tile.hair}
            skin={tile.skin}
            hairColor={tile.hairColor}
          />
        </div>
      )}
      <span className="lk-tile-label">
        {tile.label}
        {tile.speaking ? " · speaking" : ""}
      </span>
    </div>
  );
}

async function canvasAvatarTrack(label: string, hue = 18): Promise<LocalVideoTrack | null> {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const draw = (pulse = 0) => {
      const g = ctx.createLinearGradient(0, 0, 640, 480);
      g.addColorStop(0, `hsl(${hue} 42% ${18 + pulse}%)`);
      g.addColorStop(1, `hsl(${(hue + 40) % 360} 35% 10%)`);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 640, 480);
      ctx.beginPath();
      ctx.arc(320, 210, 88 + pulse * 0.4, 0, Math.PI * 2);
      ctx.fillStyle = `hsl(${hue} 55% 48%)`;
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.font = "600 36px Georgia, serif";
      ctx.textAlign = "center";
      ctx.fillText(label.slice(0, 18), 320, 380);
    };
    draw(0);
    const stream = canvas.captureStream(8);
    const track = stream.getVideoTracks()[0];
    if (!track) return null;
    return new LocalVideoTrack(track);
  } catch {
    return null;
  }
}

async function publishGreetingAudio(
  room: Room,
  audioUrl: string,
  onSpeaking?: (v: boolean) => void,
): Promise<() => void> {
  const audio = new Audio(audioUrl);
  audio.crossOrigin = "anonymous";
  audio.preload = "auto";
  await new Promise<void>((resolve, reject) => {
    audio.oncanplaythrough = () => resolve();
    audio.onerror = () => reject(new Error("Failed to load agent greeting audio"));
    void audio.load();
  });

  const media = audio as HTMLAudioElement & { captureStream?: () => MediaStream };
  let localTrack: LocalAudioTrack | null = null;
  let fallbackEl: HTMLAudioElement | null = null;

  if (typeof media.captureStream === "function") {
    const stream = media.captureStream();
    const mediaTrack = stream.getAudioTracks()[0];
    if (mediaTrack) {
      localTrack = new LocalAudioTrack(mediaTrack);
      await room.localParticipant.publishTrack(localTrack, {
        source: Track.Source.Microphone,
        name: "agent-greeting",
      });
    }
  }

  if (!localTrack) {
    fallbackEl = audio;
    try {
      const mic = await createLocalAudioTrack({ deviceId: undefined });
      await room.localParticipant.publishTrack(mic);
      localTrack = mic;
    } catch {
      /* ignore — greeting still plays via element */
    }
  }

  onSpeaking?.(true);
  await audio.play().catch(() => undefined);

  const cleanup = () => {
    onSpeaking?.(false);
    try {
      audio.pause();
    } catch {
      /* ignore */
    }
    if (localTrack) {
      void room.localParticipant.unpublishTrack(localTrack);
      localTrack.stop();
    }
    fallbackEl = null;
  };

  audio.onended = () => {
    onSpeaking?.(false);
  };

  return cleanup;
}

export default function LiveKitMeetingRoom({
  token,
  url,
  agents,
  agentPresence,
  multiAgentPresence,
  dialogue,
  spectatorMode = false,
  onDisconnect,
  onError,
  onAgentSpeakingChange,
  onAgentJoined,
  onAgentJoinFailed,
}: Props) {
  const roomRef = useRef<Room | null>(null);
  const agentRoomRef = useRef<Room | null>(null);
  const agentRoomsRef = useRef<Room[]>([]);
  const agentCleanupRef = useRef<(() => void) | null>(null);
  const agentsRef = useRef(agents);
  const presenceRef = useRef(agentPresence);
  const multiPresenceRef = useRef(multiAgentPresence);
  const dialogueRef = useRef(dialogue);
  const spectatorRef = useRef(spectatorMode);
  const onDisconnectRef = useRef(onDisconnect);
  const onErrorRef = useRef(onError);
  const onSpeakingRef = useRef(onAgentSpeakingChange);
  const onJoinedRef = useRef(onAgentJoined);
  const onJoinFailedRef = useRef(onAgentJoinFailed);
  const agentSpeakingRef = useRef(false);
  const speakingLabelRef = useRef<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [agentJoined, setAgentJoined] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [micOn, setMicOn] = useState(!spectatorMode);
  const [camOn, setCamOn] = useState(!spectatorMode);
  const [sharing, setSharing] = useState(false);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [status, setStatus] = useState(
    spectatorMode ? "Connecting as spectator…" : "Connecting to LiveKit…",
  );
  const [speakingLabel, setSpeakingLabel] = useState<string | null>(null);

  agentsRef.current = agents;
  presenceRef.current = agentPresence;
  multiPresenceRef.current = multiAgentPresence;
  dialogueRef.current = dialogue;
  spectatorRef.current = spectatorMode;
  onDisconnectRef.current = onDisconnect;
  onErrorRef.current = onError;
  onSpeakingRef.current = onAgentSpeakingChange;
  onJoinedRef.current = onAgentJoined;
  onJoinFailedRef.current = onAgentJoinFailed;

  // Only reconnect when LiveKit credentials change — parent re-renders must not drop the room.
  useEffect(() => {
    let cancelled = false;
    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
    });
    roomRef.current = room;

    const rebuild = () => {
      const agentList = agentsRef.current || [];
      const speaking = agentSpeakingRef.current;
      const next: Tile[] = [];
      const local = room.localParticipant;
      const isSpec = spectatorRef.current;
      const camPub = local.getTrackPublication(Track.Source.Camera);
      const screenPub = local.getTrackPublication(Track.Source.ScreenShare);
      if (camPub?.track) {
        next.push({
          id: "local-cam",
          label: isSpec ? `${local.name || "You"} (watching)` : local.name || "You",
          kind: "local",
          stream: new MediaStream([camPub.track.mediaStreamTrack]),
        });
      } else {
        next.push({
          id: "local-cam",
          label: isSpec ? `${local.name || "Spectator"} (watching)` : local.name || "You",
          kind: "local",
          hue: isSpec ? 200 : 160,
        });
      }
      if (screenPub?.track) {
        next.push({
          id: "local-screen",
          label: "Your screen",
          kind: "screen",
          stream: new MediaStream([screenPub.track.mediaStreamTrack]),
        });
      }
      room.remoteParticipants.forEach((p: RemoteParticipant) => {
        let hasVideo = false;
        p.trackPublications.forEach((pub: RemoteTrackPublication) => {
          if (!pub.isSubscribed && pub.isSubscribed !== undefined) {
            try {
              void pub.setSubscribed?.(true);
            } catch {
              /* older client */
            }
          }
          if (pub.kind === Track.Kind.Video && pub.track) {
            hasVideo = true;
            const isScreen = pub.source === Track.Source.ScreenShare;
            const agentMeta = agentList.find(
              (a) =>
                a.name === p.name ||
                `agent-${a.agent_type}` === p.identity ||
                a.agent_type === p.identity,
            );
            next.push({
              id: `${p.identity}-${pub.trackSid}`,
              label: isScreen ? `${p.name || p.identity} screen` : p.name || p.identity,
              kind: isScreen ? "screen" : agentMeta || p.identity.startsWith("agent-") ? "agent" : "remote",
              hue: agentMeta?.avatar_hue ?? 210,
              stream: new MediaStream([pub.track.mediaStreamTrack]),
              speaking: speaking && (agentMeta != null || p.identity.startsWith("agent-")),
            });
          }
        });
        if (!hasVideo) {
          const agentMeta = agentList.find(
            (a) => a.name === p.name || `agent-${a.agent_type}` === p.identity || a.agent_type === p.identity,
          );
          const isAgent = Boolean(agentMeta) || p.identity.startsWith("agent-");
          next.push({
            id: `remote-${p.identity}`,
            label: p.name || p.identity,
            kind: isAgent ? "agent" : "remote",
            hue: agentMeta?.avatar_hue ?? (isAgent ? 18 : 210),
            presentation: agentMeta?.avatar_presentation,
            hair: agentMeta?.avatar_hair,
            skin: agentMeta?.avatar_skin,
            hairColor: agentMeta?.avatar_hair_color,
            speaking: speaking && isAgent,
          });
        }
      });
      for (const a of agentList) {
        const already = next.some(
          (t) =>
            t.label === a.name ||
            t.id.includes(`agent-${a.agent_type}`) ||
            t.id === `agent-card-${a.agent_type}` ||
            t.id.startsWith(`remote-agent-${a.agent_type}`),
        );
        if (!already) {
          next.push({
            id: `agent-card-${a.agent_type || a.name}`,
            label: a.name,
            kind: "agent",
            hue: a.avatar_hue ?? 210,
            presentation: a.avatar_presentation,
            hair: a.avatar_hair,
            skin: a.avatar_skin,
            hairColor: a.avatar_hair_color,
            speaking: speaking && (speakingLabelRef.current === a.name || a.agent_type === "ai_calling"),
          });
        }
      }
      next.sort((a, b) => {
        const rank = (k: Tile["kind"]) => (k === "agent" ? 0 : k === "remote" ? 1 : k === "local" ? 2 : 3);
        return rank(a.kind) - rank(b.kind);
      });
      setTiles(next);
    };

    const onTrackSubscribed = (
      track: RemoteTrack,
      _pub: RemoteTrackPublication,
      participant: RemoteParticipant,
    ) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.dataset.lkAudio = "1";
        el.autoplay = true;
        document.body.appendChild(el);
        void el.play().catch(() => undefined);
        if (participant.identity.startsWith("agent-")) {
          agentSpeakingRef.current = true;
          setAgentSpeaking(true);
          speakingLabelRef.current = participant.name || participant.identity;
          setSpeakingLabel(speakingLabelRef.current);
          onSpeakingRef.current?.(true);
          track.on("ended", () => {
            agentSpeakingRef.current = false;
            setAgentSpeaking(false);
            speakingLabelRef.current = null;
            setSpeakingLabel(null);
            onSpeakingRef.current?.(false);
          });
        }
      }
      rebuild();
    };
    const onTrackUnsubscribed = (track: RemoteTrack) => {
      track.detach().forEach((el) => el.remove());
      rebuild();
    };
    const onLocalTrack = (_pub: LocalTrackPublication) => rebuild();

    room
      .on(RoomEvent.TrackSubscribed, onTrackSubscribed)
      .on(RoomEvent.TrackUnsubscribed, onTrackUnsubscribed)
      .on(RoomEvent.TrackPublished, rebuild)
      .on(RoomEvent.TrackUnpublished, rebuild)
      .on(RoomEvent.ParticipantConnected, rebuild)
      .on(RoomEvent.ParticipantDisconnected, rebuild)
      .on(RoomEvent.LocalTrackPublished, onLocalTrack)
      .on(RoomEvent.LocalTrackUnpublished, onLocalTrack)
      .on(RoomEvent.Disconnected, () => {
        setConnected(false);
        setStatus("Disconnected");
        onDisconnectRef.current?.();
      });

    void (async () => {
      try {
        await room.connect(url, token);
        if (cancelled) {
          await room.disconnect();
          return;
        }
        setConnected(true);
        const isSpec = spectatorRef.current;
        if (isSpec) {
          setStatus("Watching live — agents only (spectator)");
          setCamOn(false);
          setMicOn(false);
          try {
            await room.localParticipant.setCameraEnabled(false);
            await room.localParticipant.setMicrophoneEnabled(false);
          } catch {
            /* subscribe-only token may reject publish */
          }
        } else {
          setStatus("Live on LiveKit — waiting for agent…");
          try {
            await room.localParticipant.setCameraEnabled(true);
            await room.localParticipant.setMicrophoneEnabled(true);
            setCamOn(true);
            setMicOn(true);
          } catch {
            setCamOn(false);
            setMicOn(false);
            setStatus("Live on LiveKit (camera/mic permission limited)");
          }
        }
        rebuild();

        const multi = (multiPresenceRef.current || []).filter((p) => p?.token && p.url);
        const single = presenceRef.current;
        const presenceList: AgentPresencePayload[] =
          multi.length > 0 ? multi : single?.token && single.url ? [single] : [];

        const roomByAgent = new Map<string, Room>();
        const cleanups: Array<() => void> = [];

        for (const presence of presenceList) {
          if (!presence.token || !presence.url) continue;
          const agentRoom = new Room({ adaptiveStream: true, dynacast: true });
          agentRoomsRef.current.push(agentRoom);
          if (!agentRoomRef.current) agentRoomRef.current = agentRoom;
          try {
            await agentRoom.connect(presence.url, presence.token);
            if (cancelled) {
              await agentRoom.disconnect();
              return;
            }
            const at =
              presence.agentType ||
              presence.agent?.agent_type ||
              (presence.identity || "").replace(/^agent-/, "") ||
              "ai_calling";
            roomByAgent.set(at, agentRoom);
            const video = await canvasAvatarTrack(
              presence.name || presence.agent?.name || "Agent",
              presence.agent?.avatar_hue ?? 18,
            );
            if (video) {
              await agentRoom.localParticipant.publishTrack(video, {
                source: Track.Source.Camera,
                name: "agent-avatar",
              });
            }
          } catch (e: any) {
            const msg = e?.message || "Agent could not join LiveKit room";
            onErrorRef.current?.(msg);
            onJoinFailedRef.current?.({ timedSessionId: presence.timedSessionId, message: msg });
          }
        }

        const turns = dialogueRef.current || [];
        if (turns.length > 0 && roomByAgent.size > 0) {
          setAgentJoined(true);
          setStatus(isSpec ? "Spectator · agent dialogue live" : "Live · agent dialogue");
          onJoinedRef.current?.({
            timedSessionId: presenceList[0]?.timedSessionId || null,
          });
          // Play dialogue turns sequentially on the matching agent room
          void (async () => {
            for (const turn of turns) {
              if (cancelled) break;
              const at = turn.agent_type || "ai_calling";
              const aRoom = roomByAgent.get(at) || [...roomByAgent.values()][0];
              if (!aRoom || !turn.audioUrl) continue;
              setSpeakingLabel(turn.name || at);
              speakingLabelRef.current = turn.name || at;
              agentSpeakingRef.current = true;
              setAgentSpeaking(true);
              onSpeakingRef.current?.(true);
              rebuild();
              const speakCleanup = await publishGreetingAudio(aRoom, turn.audioUrl, (v) => {
                agentSpeakingRef.current = v;
                setAgentSpeaking(v);
                onSpeakingRef.current?.(v);
              });
              cleanups.push(speakCleanup);
              // Wait roughly for clip — publishGreetingAudio returns cleanup; poll until not speaking
              await new Promise<void>((resolve) => {
                const start = Date.now();
                const iv = window.setInterval(() => {
                  if (!agentSpeakingRef.current || Date.now() - start > 28000) {
                    window.clearInterval(iv);
                    resolve();
                  }
                }, 400);
              });
              speakingLabelRef.current = null;
              setSpeakingLabel(null);
            }
          })();
        } else if (presenceList.length === 1 && presenceList[0]) {
          const presence = presenceList[0];
          const agentRoom = roomByAgent.values().next().value as Room | undefined;
          if (agentRoom && presence.audioUrl) {
            const speakCleanup = await publishGreetingAudio(agentRoom, presence.audioUrl, (v) => {
              agentSpeakingRef.current = v;
              setAgentSpeaking(v);
              onSpeakingRef.current?.(v);
            });
            agentCleanupRef.current = speakCleanup;
          } else if (presence.greetingScript && "speechSynthesis" in window) {
            const utter = new SpeechSynthesisUtterance(presence.greetingScript);
            utter.onstart = () => {
              agentSpeakingRef.current = true;
              setAgentSpeaking(true);
              onSpeakingRef.current?.(true);
            };
            utter.onend = () => {
              agentSpeakingRef.current = false;
              setAgentSpeaking(false);
              onSpeakingRef.current?.(false);
            };
            window.speechSynthesis.speak(utter);
          }
          setAgentJoined(true);
          setStatus(
            isSpec
              ? "Watching · agents in room"
              : presence.maxCallSeconds
                ? `Live with agent · timed budget ${presence.maxCallSeconds}s`
                : "Live with agent on the other side",
          );
          onJoinedRef.current?.({ timedSessionId: presence.timedSessionId });
          rebuild();
        } else if (presenceList.length > 0) {
          setAgentJoined(true);
          setStatus(isSpec ? "Watching · agents connected" : "Live with agents");
          onJoinedRef.current?.({ timedSessionId: presenceList[0]?.timedSessionId });
          rebuild();
        }

        agentCleanupRef.current = () => {
          for (const c of cleanups) {
            try {
              c();
            } catch {
              /* ignore */
            }
          }
        };
      } catch (e: any) {
        const msg = e?.message || "LiveKit connect failed";
        setStatus(msg);
        onErrorRef.current?.(msg);
      }
    })();

    return () => {
      cancelled = true;
      try {
        agentCleanupRef.current?.();
      } catch {
        /* ignore */
      }
      agentCleanupRef.current = null;
      for (const ar of agentRoomsRef.current) {
        void ar.disconnect();
      }
      agentRoomsRef.current = [];
      void agentRoomRef.current?.disconnect();
      agentRoomRef.current = null;
      room.removeAllListeners();
      room.remoteParticipants.forEach((p) => {
        p.trackPublications.forEach((pub: TrackPublication) => {
          if (pub.track) pub.track.detach().forEach((el) => el.remove());
        });
      });
      void room.disconnect();
      roomRef.current = null;
      document.querySelectorAll("[data-lk-audio]").forEach((el) => el.remove());
    };
  }, [token, url]);

  useEffect(() => {
    agentSpeakingRef.current = agentSpeaking;
    setTiles((prev) =>
      prev.map((t) => ({
        ...t,
        speaking: Boolean(
          agentSpeaking &&
            (t.kind === "agent" || t.id.includes("agent-")) &&
            (!speakingLabel || t.label === speakingLabel || t.label.startsWith(speakingLabel)),
        ),
      })),
    );
  }, [agentSpeaking, speakingLabel]);

  async function toggleMic() {
    const room = roomRef.current;
    if (!room || spectatorMode) return;
    const next = !micOn;
    await room.localParticipant.setMicrophoneEnabled(next);
    setMicOn(next);
  }

  async function toggleCam() {
    const room = roomRef.current;
    if (!room || spectatorMode) return;
    const next = !camOn;
    await room.localParticipant.setCameraEnabled(next);
    setCamOn(next);
  }

  async function toggleShare() {
    const room = roomRef.current;
    if (!room || spectatorMode) return;
    try {
      if (sharing) {
        await room.localParticipant.setScreenShareEnabled(false);
        setSharing(false);
      } else {
        await room.localParticipant.setScreenShareEnabled(true);
        setSharing(true);
      }
    } catch (e: any) {
      onError?.(e?.message || "Screen share failed");
    }
  }

  async function leave() {
    try {
      agentCleanupRef.current?.();
    } catch {
      /* ignore */
    }
    for (const ar of agentRoomsRef.current) {
      await ar.disconnect();
    }
    agentRoomsRef.current = [];
    await agentRoomRef.current?.disconnect();
    await roomRef.current?.disconnect();
    onDisconnect?.();
  }

  return (
    <section className="lk-room">
      <div className="lk-room-head">
        <p className="lk-status">{status}</p>
        {spectatorMode ? <span className="pill">Spectator</span> : null}
        {connected ? <span className="pill ok">You connected</span> : <span className="pill warn">Connecting</span>}
        {agentJoined ? (
          <span className={`pill ${agentSpeaking ? "ok" : ""}`}>
            {agentSpeaking
              ? `${speakingLabel || "Agent"} speaking`
              : spectatorMode
                ? "Agents in room"
                : "Agent in room"}
          </span>
        ) : (
          <span className="pill">Agent joining…</span>
        )}
      </div>
      <div className="lk-grid lk-grid-meeting">
        {tiles.map((t) => (
          <VideoTile key={t.id} tile={t} />
        ))}
      </div>
      <div className="lk-controls">
        {!spectatorMode ? (
          <>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void toggleMic()} disabled={!connected}>
              {micOn ? "Mute" : "Unmute"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void toggleCam()} disabled={!connected}>
              {camOn ? "Camera off" : "Camera on"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void toggleShare()} disabled={!connected}>
              {sharing ? "Stop share" : "Share screen"}
            </button>
          </>
        ) : (
          <span className="muted" style={{ fontSize: "0.85rem" }}>
            Mic &amp; camera stay off in spectator mode
          </span>
        )}
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void leave()}>
          Leave room
        </button>
      </div>
    </section>
  );
}
