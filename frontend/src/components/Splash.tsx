import { useCallback, useEffect, useState } from "react";

type SplashProps = {
  onComplete: () => void;
};

type Phase = "logo" | "cinematic" | "brand" | "tagline" | "loading" | "done";

/** Cinematic startup: logo → brand → tagline → loading → dashboard. No AI host. */
export default function Splash({ onComplete }: SplashProps) {
  const [phase, setPhase] = useState<Phase>("logo");
  const [loadPct, setLoadPct] = useState(0);

  const finish = useCallback(() => {
    setPhase("done");
    onComplete();
  }, [onComplete]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key.toLowerCase() === "s") finish();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finish]);

  useEffect(() => {
    const t1 = window.setTimeout(() => setPhase("cinematic"), 900);
    const t2 = window.setTimeout(() => setPhase("brand"), 1700);
    const t3 = window.setTimeout(() => setPhase("tagline"), 2500);
    const t4 = window.setTimeout(() => setPhase("loading"), 3400);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      window.clearTimeout(t3);
      window.clearTimeout(t4);
    };
  }, []);

  useEffect(() => {
    if (phase !== "loading") return;
    let p = 0;
    const id = window.setInterval(() => {
      p += 8 + Math.floor(Math.random() * 7);
      if (p >= 100) {
        p = 100;
        setLoadPct(100);
        window.clearInterval(id);
        window.setTimeout(finish, 400);
      } else {
        setLoadPct(p);
      }
    }, 85);
    return () => window.clearInterval(id);
  }, [phase, finish]);

  return (
    <div className="splash" role="status" aria-live="polite">
      <div className="splash-orb splash-orb-a" aria-hidden />
      <div className="splash-orb splash-orb-b" aria-hidden />
      <div className="splash-scan" aria-hidden />
      <button type="button" className="splash-skip" onClick={finish}>
        Skip
      </button>

      <div className="splash-center">
        <img
          className={`splash-logo phase-${phase}`}
          src="/veridiq-logo.svg"
          alt="VERIDIQ"
          width={120}
          height={120}
        />
        <h1 className={`splash-brand ${phase === "logo" || phase === "cinematic" ? "is-hidden" : "is-in"}`}>
          VERIDIQ
        </h1>
        <p className={`splash-tag ${["tagline", "loading", "done"].includes(phase) ? "is-in" : "is-hidden"}`}>
          Truth. Verified. Empowered.
        </p>
        {phase === "loading" || phase === "done" ? (
          <div className="splash-load" aria-label={`Loading ${loadPct}%`}>
            <div className="splash-load-bar">
              <span style={{ width: `${loadPct}%` }} />
            </div>
            <p className="muted">Initializing enterprise systems…</p>
          </div>
        ) : null}
      </div>

      <style>{`
        .splash {
          position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center;
          background:
            radial-gradient(800px 480px at 28% 18%, rgba(79,140,255,.28), transparent 58%),
            radial-gradient(700px 420px at 78% 72%, rgba(177,77,255,.22), transparent 55%),
            linear-gradient(160deg, #05070F 0%, #0B1224 55%, #05070F 100%);
          overflow: hidden;
        }
        .splash-scan {
          position: absolute; inset: -20% 0 auto; height: 40%;
          background: linear-gradient(180deg, transparent, rgba(79,140,255,.08), transparent);
          animation: scanMove 3.8s ease-in-out infinite;
          pointer-events: none;
        }
        @keyframes scanMove {
          0% { transform: translateY(0); opacity: 0.2; }
          50% { opacity: 0.55; }
          100% { transform: translateY(160vh); opacity: 0.15; }
        }
        .splash-skip {
          position: absolute; top: 1.1rem; right: 1.1rem; z-index: 2;
          border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04);
          color: #9AA6BF; border-radius: 999px; padding: 0.45rem 0.9rem; font-size: 0.8rem;
        }
        .splash-center { text-align: center; padding: 1.5rem; max-width: 40rem; position: relative; z-index: 1; }
        .splash-logo {
          width: 120px; height: 120px; margin: 0 auto 1.35rem; display: block;
          animation: logoIn 1.15s cubic-bezier(.2,.8,.2,1) both, pulseGlow 2.8s ease-in-out infinite;
          filter: drop-shadow(0 0 28px rgba(79,140,255,0.35));
        }
        .splash-logo.phase-cinematic {
          transform: scale(1.08);
          transition: transform 800ms ease;
        }
        .splash-brand {
          margin: 0; font-size: clamp(2.6rem, 7vw, 4rem); font-weight: 700; letter-spacing: 0.2em;
          background: linear-gradient(120deg, #F7F9FC, #4F8CFF 48%, #B14DFF);
          -webkit-background-clip: text; background-clip: text; color: transparent;
          transition: opacity 700ms ease, transform 700ms ease;
        }
        .splash-brand.is-hidden { opacity: 0; transform: translateY(12px); }
        .splash-brand.is-in { opacity: 1; transform: none; animation: fadeUp 700ms ease both; }
        .splash-tag {
          margin: 0.95rem 0 1.5rem; color: #9AA6BF; letter-spacing: 0.24em; text-transform: uppercase;
          font-size: 0.78rem; font-weight: 500; transition: opacity 600ms ease, transform 600ms ease;
        }
        .splash-tag.is-hidden { opacity: 0; transform: translateY(8px); }
        .splash-tag.is-in { opacity: 1; transform: none; }
        .splash-load { margin-top: 1.1rem; width: min(280px, 70vw); margin-left: auto; margin-right: auto; }
        .splash-load-bar {
          height: 3px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; margin-bottom: 0.65rem;
        }
        .splash-load-bar span {
          display: block; height: 100%; border-radius: inherit;
          background: linear-gradient(90deg, #4F8CFF, #B14DFF);
          transition: width 120ms linear;
        }
        .splash-load .muted { margin: 0; font-size: 0.78rem; color: #9AA6BF; }
        .splash-orb {
          position: absolute; border-radius: 50%; filter: blur(48px); opacity: 0.42; pointer-events: none;
        }
        .splash-orb-a { width: 300px; height: 300px; left: 6%; top: 14%; background: #4F8CFF; animation: orbFloat 7s ease-in-out infinite; }
        .splash-orb-b { width: 260px; height: 260px; right: 8%; bottom: 12%; background: #B14DFF; animation: orbFloat 8s ease-in-out infinite reverse; }
        @keyframes orbFloat {
          0%, 100% { transform: translate(0,0) scale(1); }
          50% { transform: translate(12px,-18px) scale(1.06); }
        }
        @media (prefers-reduced-motion: reduce) {
          .splash-scan, .splash-orb-a, .splash-orb-b, .splash-logo { animation: none; }
        }
      `}</style>
    </div>
  );
}
