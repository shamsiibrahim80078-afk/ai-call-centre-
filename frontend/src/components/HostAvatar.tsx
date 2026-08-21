import { useEffect, useState } from "react";

type HostAvatarProps = {
  speaking?: boolean;
  phase: string;
};

/** Holographic AI Host — blink, breathe, glance, lip cue, light rim. */
export default function HostAvatar({ speaking = false, phase }: HostAvatarProps) {
  const [blink, setBlink] = useState(false);
  const [glance, setGlance] = useState(0);
  const [gesture, setGesture] = useState(0);

  useEffect(() => {
    const blinkId = window.setInterval(() => {
      setBlink(true);
      window.setTimeout(() => setBlink(false), 140);
    }, 2800 + Math.random() * 2000);
    const glanceId = window.setInterval(() => setGlance((g) => (g + 1) % 3), 3800);
    const gestureId = window.setInterval(() => setGesture((g) => (g + 1) % 4), 5200);
    return () => {
      window.clearInterval(blinkId);
      window.clearInterval(glanceId);
      window.clearInterval(gestureId);
    };
  }, []);

  const eyeOffset = glance === 1 ? 2.8 : glance === 2 ? -2.8 : 0;
  const mouthOpen = speaking ? 4 + (gesture % 2) * 2 : 1.4;
  const tilt = gesture === 1 ? 2 : gesture === 2 ? -2 : 0;

  return (
    <div className={`host-avatar ${speaking ? "is-speaking" : ""}`} aria-hidden>
      <div className="holo-ring" />
      <svg viewBox="0 0 120 120" width="128" height="128" role="presentation" style={{ transform: `rotate(${tilt}deg)` }}>
        <defs>
          <linearGradient id="hostRing" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#4F8CFF" />
            <stop offset="0.5" stopColor="#7B5CFF" />
            <stop offset="1" stopColor="#B14DFF" />
          </linearGradient>
          <radialGradient id="hostFace" cx="45%" cy="35%" r="65%">
            <stop stopColor="#243556" />
            <stop offset="0.55" stopColor="#121c33" />
            <stop offset="1" stopColor="#070b16" />
          </radialGradient>
          <filter id="softGlow">
            <feGaussianBlur stdDeviation="2.2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <circle className="host-glow" cx="60" cy="60" r="56" fill="url(#hostRing)" opacity="0.18" />
        <circle cx="60" cy="60" r="47" fill="url(#hostFace)" stroke="url(#hostRing)" strokeWidth="2.4" filter="url(#softGlow)" />
        <path d="M28 78 Q60 98 92 78" fill="none" stroke="rgba(79,140,255,0.25)" strokeWidth="1" />
        <g transform={`translate(${eyeOffset} 0)`}>
          <ellipse cx="46" cy="52" rx="6.2" ry={blink ? 0.7 : 5.4} fill="#E8EEFF" />
          <ellipse cx="74" cy="52" rx="6.2" ry={blink ? 0.7 : 5.4} fill="#E8EEFF" />
          {!blink && (
            <>
              <circle cx="47.6" cy="53" r="2.5" fill="#05070F" />
              <circle cx="75.6" cy="53" r="2.5" fill="#05070F" />
              <circle cx="48.5" cy="51.8" r="0.75" fill="#fff" />
              <circle cx="76.5" cy="51.8" r="0.75" fill="#fff" />
            </>
          )}
        </g>
        <path
          d={`M48 72 Q60 ${72 + mouthOpen} 72 72`}
          fill="none"
          stroke="#A9B7D6"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
      </svg>
      <span className="host-phase">{phase}</span>
      <style>{`
        .host-avatar {
          position: relative;
          display: grid;
          justify-items: center;
          gap: 0.45rem;
          animation: hostBreathe 3.8s ease-in-out infinite;
        }
        .holo-ring {
          position: absolute; inset: 8px auto auto 50%; width: 112px; height: 112px; margin-left: -56px;
          border-radius: 50%; border: 1px solid rgba(79,140,255,0.35);
          box-shadow: 0 0 28px rgba(79,140,255,0.25), inset 0 0 24px rgba(177,77,255,0.12);
          animation: holoSpin 10s linear infinite;
          pointer-events: none;
        }
        .host-avatar.is-speaking .host-glow { animation: hostPulse 0.9s ease-in-out infinite; }
        .host-avatar svg { transition: transform 600ms ease; }
        .host-phase {
          font-size: 0.68rem; letter-spacing: 0.16em; text-transform: uppercase; color: #9AA6BF;
        }
        @keyframes hostBreathe {
          0%, 100% { transform: translateY(0) scale(1); }
          50% { transform: translateY(-4px) scale(1.02); }
        }
        @keyframes hostPulse {
          0%, 100% { opacity: 0.16; }
          50% { opacity: 0.4; }
        }
        @keyframes holoSpin {
          to { transform: rotate(360deg); }
        }
        @media (prefers-reduced-motion: reduce) {
          .host-avatar, .holo-ring, .host-avatar.is-speaking .host-glow { animation: none; }
        }
      `}</style>
    </div>
  );
}
