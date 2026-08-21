"""CLI for the zero-cost VERIDIQ free media pipeline.

Usage:
  python scripts/free_media_agent.py --topic "Bitcoin rally" --voice en-US-AriaNeural
  python scripts/free_media_agent.py --topic "ETH ETF" --script "Custom VO..." --count 2 --out marketing_out/free_media

Dependencies (free):
  pip install moviepy edge-tts pillow
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pillow ≥10 removed ANTIALIAS; MoviePy 1.0.3 still needs it.
try:
    from PIL import Image as _PILImage

    if not hasattr(_PILImage, "ANTIALIAS"):
        _PILImage.ANTIALIAS = _PILImage.Resampling.LANCZOS  # type: ignore[attr-defined]
except Exception:
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="VERIDIQ zero-cost media: Pollinations stills + MoviePy + edge-tts",
    )
    parser.add_argument("--topic", required=True, help="Crypto / marketing topic for images + default script")
    parser.add_argument("--script", default=None, help="Optional voiceover script (defaults from topic)")
    parser.add_argument("--count", type=int, default=3, help="Number of stills (1–8, default 3)")
    parser.add_argument("--voice", default="en-US-AriaNeural", help="edge-tts voice id")
    parser.add_argument(
        "--out",
        default=None,
        help="Output root (default: marketing_out/free_media with images/, audio/, videos/)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=4.0,
        help="Seconds per still before concat (default 4)",
    )
    args = parser.parse_args(argv)

    from veridiq.postings.free_media_pipeline import run_pipeline

    result = run_pipeline(
        topic=args.topic,
        script=args.script,
        out_dir=args.out,
        count=args.count,
        voice=args.voice,
        duration_per_image=args.duration,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
