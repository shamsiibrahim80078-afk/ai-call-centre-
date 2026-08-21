"""High-fidelity narration TTS + audio mastering for video mux.

Fallback chain: ElevenLabs → Azure Speech → edge-tts neural.

True facial phoneme / lip-sync keypoints are NOT implemented here.
Stills-slideshow video cannot drive real lip sync; that needs a talking-head
model. We only align audio duration to video length (trim/pad) at mux time.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
AUD_DIR = _ROOT / "marketing_out" / "audio"

# Target VO delivery for mux
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2  # stereo
AAC_BITRATE = "160k"


def _elevenlabs_key() -> str:
    return (
        (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        or (os.getenv("VERIDIQ_ELEVENLABS_API_KEY") or "").strip()
    )


def _azure_speech_key() -> str:
    return (
        (os.getenv("AZURE_SPEECH_KEY") or "").strip()
        or (os.getenv("VERIDIQ_AZURE_SPEECH_KEY") or "").strip()
        or (os.getenv("AZURE_TTS_KEY") or "").strip()
    )


def _azure_speech_region() -> str:
    return (
        (os.getenv("AZURE_SPEECH_REGION") or "").strip()
        or (os.getenv("VERIDIQ_AZURE_SPEECH_REGION") or "").strip()
        or (os.getenv("AZURE_TTS_REGION") or "").strip()
        or "eastus"
    )


def _ffmpeg_exe() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _clean_script(script: str) -> str:
    text = re.sub(r"\s+", " ", (script or "").strip())
    text = re.sub(r"\[Scene\s+\d+\]\s*", "", text)
    return text[:1200]


def _try_elevenlabs(text: str, path: Path) -> Optional[str]:
    """ElevenLabs neural TTS when API key present. Returns voice id used or None."""
    key = _elevenlabs_key()
    if not key:
        return None
    try:
        import requests

        voice_id = (
            (os.getenv("ELEVENLABS_VOICE_ID") or "").strip()
            or (os.getenv("VERIDIQ_ELEVENLABS_VOICE_ID") or "").strip()
            or "21m00Tcm4TlvDq8ikWAM"  # Rachel — clear female neural default
        )
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        resp = requests.post(
            url,
            headers={
                "xi-api-key": key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": (os.getenv("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2").strip(),
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        if resp.status_code == 200 and len(resp.content) > 400:
            path.write_bytes(resp.content)
            return voice_id
    except Exception:
        return None
    return None


def _try_azure(text: str, path: Path) -> Optional[str]:
    """Azure Cognitive Services Speech TTS when key+region present."""
    key = _azure_speech_key()
    region = _azure_speech_region()
    if not key:
        return None
    try:
        import requests

        voice = (
            (os.getenv("AZURE_SPEECH_VOICE") or "").strip()
            or (os.getenv("VERIDIQ_AZURE_SPEECH_VOICE") or "").strip()
            or "en-US-JennyNeural"
        )
        ssml = (
            f"<speak version='1.0' xml:lang='en-US'>"
            f"<voice name='{voice}'>{_xml_escape(text)}</voice></speak>"
        )
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        resp = requests.post(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-48khz-192kbitrate-mono-mp3",
                "User-Agent": "VERIDIQ-Postings",
            },
            data=ssml.encode("utf-8"),
            timeout=60,
        )
        if resp.status_code == 200 and len(resp.content) > 400:
            path.write_bytes(resp.content)
            return voice
    except Exception:
        return None
    return None


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _try_edge_tts(text: str, path: Path) -> Optional[str]:
    """edge-tts neural voices (free fallback)."""
    try:
        import asyncio
        import edge_tts

        voices = (
            "en-US-AriaNeural",
            "en-US-JennyNeural",
            "en-US-MichelleNeural",
            "en-GB-SoniaNeural",
        )

        async def _run() -> str:
            last_err = ""
            for voice in voices:
                try:
                    communicate = edge_tts.Communicate(text, voice, rate="-2%", pitch="+0Hz")
                    await communicate.save(str(path))
                    if path.exists() and path.stat().st_size > 400:
                        return voice
                except Exception as exc:
                    last_err = str(exc)[:80]
            raise RuntimeError(last_err or "All edge-tts voices failed")

        return asyncio.run(_run())
    except Exception:
        return None


def generate_narration(
    *,
    script: str,
    duration_hint_sec: int = 15,
) -> dict[str, Any]:
    """Synthesize VO via optional paid TTS if keys exist, else free edge-tts.

    Chain: ElevenLabs (if key) → Azure Speech (if key) → edge-tts neural (free).
    Keys are never required. Note: No facial lip-sync / phoneme keypoints —
    slideshow stills cannot drive mouth shapes. Duration alignment happens at mux.
    """
    AUD_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    text = _clean_script(script)
    if not text:
        return {"ok": False, "status": "error", "message": "Empty narration script."}

    path = AUD_DIR / f"vidnarr_{sid}.mp3"
    provider = ""
    voice_used = ""

    el = _try_elevenlabs(text, path)
    if el and path.exists() and path.stat().st_size > 400:
        provider, voice_used = "elevenlabs", el
    else:
        az = _try_azure(text, path)
        if az and path.exists() and path.stat().st_size > 400:
            provider, voice_used = "azure_speech", az
        else:
            edge = _try_edge_tts(text, path)
            if edge and path.exists() and path.stat().st_size > 400:
                provider, voice_used = "edge_tts", edge

    if not provider or not path.exists():
        return {"ok": False, "status": "error", "message": "Narration unavailable (all TTS providers failed)."}

    # Optional: remaster to 48kHz stereo WAV intermediate (PCM 24-bit when ffmpeg allows)
    mastered = master_audio_file(path)
    out = mastered if mastered and mastered.exists() else path

    return {
        "ok": True,
        "status": "ok",
        "absolute_path": str(out),
        "audio_path": str(out.relative_to(_ROOT)).replace("\\", "/"),
        "audio_url": f"/api/v1/veridiq/marketing/audio/file/{out.name}",
        "message": f"Narration via {provider} ({voice_used}).",
        "provider": provider,
        "voice": voice_used,
        "duration_hint_sec": duration_hint_sec,
        "sample_rate": TARGET_SAMPLE_RATE,
        "channels": TARGET_CHANNELS,
        # Honest: true phoneme lip-sync needs a talking-head model, not stills.
        "lip_sync": False,
        "lip_sync_note": (
            "Facial phoneme / lip-sync keypoints not applied — "
            "stills slideshow cannot drive mouth shapes; needs talking-head model."
        ),
    }


def master_audio_file(src: Path) -> Optional[Path]:
    """Light mastering → 48kHz stereo AAC/WAV when ffmpeg available."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not src.is_file():
        return None
    out = src.with_name(src.stem + "_48k.wav")
    try:
        # soft highpass + mild room reverb + loudnorm + stereo 48kHz; PCM 24-bit intermediate
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-af",
                "highpass=f=80,aecho=0.8:0.88:40:0.18,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar",
                str(TARGET_SAMPLE_RATE),
                "-ac",
                str(TARGET_CHANNELS),
                "-c:a",
                "pcm_s24le",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if out.exists() and out.stat().st_size > 400:
            return out
    except Exception:
        return None
    return None


def master_and_fit_audio(
    audio_path: Path,
    *,
    target_duration_sec: float,
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    """Trim or pad narration so VO length matches video; 48kHz stereo.

    Does NOT attempt facial lip-sync — only duration alignment for mux.
    """
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not audio_path.is_file():
        return None
    target = max(1.0, float(target_duration_sec))
    dest = out_path or audio_path.with_name(audio_path.stem + f"_fit{int(target)}s.wav")
    try:
        # apad + atrim: pad silence if short, then hard-trim to exact length
        # mild aecho = natural room reverb / studio warmth (3-pillars acoustics)
        filt = (
            f"silenceremove=start_periods=1:start_silence=0.02:start_threshold=-38dB,"
            f"highpass=f=80,aecho=0.8:0.88:40:0.18,loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"apad=pad_dur={target + 1.0},atrim=0:{target}"
        )
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(audio_path),
                "-af",
                filt,
                "-ar",
                str(TARGET_SAMPLE_RATE),
                "-ac",
                str(TARGET_CHANNELS),
                "-c:a",
                "pcm_s24le",
                "-t",
                str(target),
                str(dest),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        if dest.exists() and dest.stat().st_size > 400:
            return dest
    except Exception:
        return None
    return None


def probe_wav_duration_sec(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:
        return None
