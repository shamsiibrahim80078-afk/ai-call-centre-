"""Mira local stills — branded cards for VERIDIQ; topic-aware creative locals.

Brand / VERIDIQ topics: short titled cards (VERIDIQ / Truth. Verified. / AI Workforce).
Creative topics (gym, dog, car, stories): never dump the user prompt onto a title card —
prefer Pollinations AI; if AI fails, topic-aware local illustrations (centered subject
on a rich themed scenic background), not bare abstract color pads.

Character topics (fruits / animals / people / speak-talk-describe): NEVER pad with
abstract blur gradients. Fruit topics use render_talking_fruit_stills() — clear
cartoon Apple / Banana / Orange with faces on a cozy kitchen background.
ZERO Pollinations / ZERO abstract pads for fruit topics.

Opening-shot policy:
  - Brand: frame 0 is premium local hero (VERIDIQ wordmark).
  - Fruit: local drawn fruit stills (talking mouth pairs when speak).
  - Other creative: prefer AI stills; pad with topic-aware local illustrations.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
IMG_DIR = _ROOT / "marketing_out" / "images"

_W = 1280
_H = 720

# Midnight + electric blue brand palette
_BG_TOP = (6, 12, 28)
_BG_BOT = (10, 28, 58)
_ACCENT = (56, 168, 255)
_ACCENT_DIM = (28, 90, 160)
_TITLE = (240, 248, 255)
_SUB = (170, 198, 230)
_MUTED = (120, 150, 190)
_CARD = (14, 26, 48)
_CARD_EDGE = (40, 110, 190)

# Creative abstract palettes (scene-colored, no readable prompt)
_ABSTRACT_PALETTES = (
    ((18, 42, 28), (48, 120, 72), (90, 180, 110)),  # orchard green
    ((48, 28, 12), (140, 90, 30), (220, 160, 60)),  # warm fruit gold
    ((22, 18, 48), (60, 40, 120), (120, 90, 200)),  # dusk violet
    ((12, 36, 52), (30, 90, 130), (70, 160, 200)),  # sky teal
    ((40, 16, 24), (110, 40, 55), (190, 80, 90)),  # berry red
)

# Fruit cast (order matches VO script)
_FRUIT_KINDS = ("apple", "banana", "orange")
_MOUTH_HOLD_SEC = 0.45

# Drawable local illustration subjects (keyword → canonical kind)
# Order matters for first-match in detect_illustration_subject.
_ILLUSTRATION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("robot", "robot"),
    ("android", "robot"),
    ("dog", "dog"),
    ("puppy", "dog"),
    ("cat", "cat"),
    ("kitten", "cat"),
    ("bird", "bird"),
    ("eagle", "bird"),
    ("car", "car"),
    ("truck", "car"),
    ("vehicle", "car"),
    ("gym", "gym"),
    ("workout", "gym"),
    ("fitness", "gym"),
    ("athlete", "gym"),
    ("bodybuilder", "gym"),
    ("dragon", "dragon"),
    ("rocket", "rocket"),
    ("astronaut", "rocket"),
    ("space", "rocket"),
    ("beach", "beach"),
    ("ocean", "beach"),
    ("mountain", "mountain"),
    ("forest", "forest"),
    ("tree", "forest"),
    ("house", "house"),
    ("home", "house"),
    ("boat", "boat"),
    ("ship", "boat"),
    ("train", "train"),
    ("plane", "plane"),
    ("airplane", "plane"),
    ("lion", "lion"),
    ("tiger", "lion"),
    ("bear", "bear"),
    ("fox", "fox"),
    ("wolf", "fox"),
    ("horse", "horse"),
    ("boy", "person"),
    ("girl", "person"),
    ("man", "person"),
    ("woman", "person"),
    ("person", "person"),
    ("people", "person"),
    ("human", "person"),
    ("character", "person"),
)

# Subjects that get a face + mouth open/close for speak/talk topics
_FACE_SUBJECTS = frozenset(
    {"dog", "cat", "bird", "robot", "dragon", "lion", "bear", "fox", "horse", "person", "gym"}
)


def _is_veridiq_topic(topic: str) -> bool:
    """Prefer creative.is_brand_topic (shared keywords); keep a local fallback."""
    try:
        from veridiq.postings.creative import is_brand_topic

        return is_brand_topic(topic)
    except Exception:
        t = (topic or "").lower()
        return bool(
            re.search(
                r"\bver+i?diq\b|\bverdiq\b|\bveridig\b|\bv[e]?rid[iq]g?\b|"
                r"\bagents?\s+workspace\b|\bai\s+workforce\b|\btruth\s+verif|"
                r"\bour\s+product\b|\bexplain\s+what\s+ver|\bwhat\s+is\s+ver",
                t,
            )
        )


def is_fruit_topic(topic: str) -> bool:
    """True when the ask is about fruits (incl. common typos like froot)."""
    t = (topic or "").lower()
    return bool(
        re.search(
            r"\bfruits?\b|\bfroots?\b|\bapple|\bbanana|\borange|"
            r"\banthropomorphic\s+fruit|"
            r"talking\s+fruit|fruit\s+character|cartoon\s+fruit",
            t,
        )
    )


def wants_speaking(topic: str) -> bool:
    """True when the user wants visible talking / describing characters."""
    try:
        from veridiq.postings.creative import wants_character_dialogue

        return wants_character_dialogue(topic)
    except Exception:
        t = (topic or "").lower()
        return bool(
            re.search(
                r"\b(talking|talk|speak|speaking|dialogue|conversation|"
                r"describe|describing|themselves|each other|introduc|voice)\b",
                t,
            )
        )


def is_character_topic(topic: str) -> bool:
    """Fruits / animals / people / speak-describe — never abstract-gradient pad."""
    t = (topic or "").lower()
    if is_fruit_topic(t) or wants_speaking(t):
        return True
    return bool(
        re.search(
            r"\b(animals?|dogs?|cats?|birds?|people|person|human|boy|girl|"
            r"man|woman|character|cast)\b",
            t,
        )
    )


def _looks_like_command(text: str) -> bool:
    """True when leftover still reads like a user instruction, not a short title."""
    t = (text or "").strip().lower()
    if not t:
        return True
    if len(t) > 40:
        return True
    if re.search(
        r"\b(create|make|generate|render|write|produce|build|please|can you|i want|"
        r"for my|for me|in that|tell what|explain what|describ\w*|introduc\w*|"
        r"identity|themselves|every\b)\b",
        t,
    ):
        return True
    # Long multi-clause leftovers (commas / "and then" / periods) → not a title
    if t.count(",") >= 2 or t.count(".") >= 1 or " and then " in t:
        return True
    # Multi-word creative sentences (≥4 words) must never become on-screen titles
    if len(t.split()) >= 4:
        return True
    return False


def _clean_topic_title(topic: str) -> str:
    """Short on-frame title for *brand* cards only — never raw user commands.

    For creative (non-brand) topics returns "" so callers never paint the prompt.
    Brand topics resolve to VERIDIQ / short product labels via frame_copy_for_topic.
    """
    raw = re.sub(r"\s+", " ", (topic or "").strip())
    # Strip common create-video / make-a boilerplate (leading + mid-string)
    raw = re.sub(
        r"^(please\s+)?(can you\s+)?(create|make|generate|render|produce|build)\s+"
        r"(a\s+|an\s+|me\s+a\s+|me\s+an\s+)?"
        r"(long\s+|short\s+|quick\s+)?"
        r"(video|clip|reel|mp4|film|movie|animation)?\s*"
        r"(for|about|of|on|with|showing)?\s*",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(
        r"\b(create|make|generate|render)\s+(a\s+|an\s+)?(video|clip|reel|mp4)\b",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\bfor\s+my\b|\bfor\s+me\b", " ", raw, flags=re.I)
    raw = re.sub(
        r"\b(in that|that\s+)?(tell|explain|describ\w*)\s+(what|about)\s+",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\b(my|the|a|an)\s+", " ", raw, flags=re.I)
    # Never keep scene indices in titles
    raw = re.sub(r"\bscene\s*(?:one|two|three|\d+)\b", "", raw, flags=re.I)
    # Drop trailing media-type leftovers ("gym boy video" → "gym boy")
    raw = re.sub(
        r"\s+(long\s+|short\s+)?(videos?|clips?|reels?|mp4|films?|movies?|animations?)\s*$",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\s+", " ", raw).strip(" .,-:;!?\"'")

    if _is_veridiq_topic(topic) or _is_veridiq_topic(raw):
        return "VERIDIQ"
    # Creative / non-brand: never surface cleaned prompt as a multi-word title
    if not raw or _looks_like_command(raw):
        return ""
    # Title-case short phrases (≤40 chars, ≤3 words) for rare short creative labels
    words = []
    for w in raw.split()[:3]:
        if re.match(r"^ver+i?diq$|^verdiq$|^veridig$", w, re.I):
            words.append("VERIDIQ")
        else:
            words.append(w[:1].upper() + w[1:] if w else w)
    title = " ".join(words).strip()
    if not title or len(title) > 40 or _looks_like_command(title) or len(title.split()) >= 4:
        return ""
    return title


def frame_copy_for_topic(topic: str, n: int = 3) -> list[dict[str, str]]:
    """Return n frame descriptors.

    Brand → titled VERIDIQ cards.
    Fruit → fruit character layouts (never abstract).
    Other creative → topic-aware illustration (no main title / no prompt text).
    """
    if _is_veridiq_topic(topic):
        frames = [
            {
                "eyebrow": "",
                "title": "VERIDIQ",
                "subtitle": "Truth. Verified. Empowered.",
                "footer": "",
                "layout": "hero",
            },
            {
                "eyebrow": "VERIDIQ",
                "title": "Truth verification",
                "subtitle": "Evidence-backed claims",
                "footer": "Investigate · report · trust",
                "layout": "card",
            },
            {
                "eyebrow": "VERIDIQ",
                "title": "AI Workforce",
                "subtitle": "Agents in one workspace",
                "footer": "Live agent workspace",
                "layout": "card",
            },
        ]
    elif is_fruit_topic(topic) or (
        is_character_topic(topic) and wants_speaking(topic) and is_fruit_topic(topic)
    ):
        # Fruit characters — no prompt text on frame
        kinds = _FRUIT_KINDS
        frames = [
            {
                "eyebrow": "",
                "title": "",
                "subtitle": "",
                "footer": "",
                "layout": "fruit",
                "fruit": kinds[i % len(kinds)],
            }
            for i in range(max(1, n))
        ]
    else:
        # Creative: topic-aware illustration — never dump prompt as title
        subj = detect_illustration_subject(topic)
        frames = [
            {
                "eyebrow": "",
                "title": "",
                "subtitle": "",
                "footer": "",
                "layout": "illustration",
                "subject": subj,
            }
            for _ in range(max(1, n))
        ]
    while len(frames) < max(1, n):
        last = frames[-1]
        frames.append({**last, "layout": last.get("layout") or "card"})
    return frames[: max(1, n)]


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _draw_gradient(img: Any, top: tuple[int, int, int], bot: tuple[int, int, int]) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        c = _lerp(top, bot, y / max(1, h - 1))
        draw.line([(0, y), (w, y)], fill=c)


def _load_font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_text(draw: Any, text: str, font: Any, max_width: int) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # Hard ban scene labels / prompt dumps on frames
    if re.search(r"\bscene\s*\d+\b", t, re.I):
        t = re.sub(r"\bscene\s*\d+\b", "", t, flags=re.I).strip() or "VERIDIQ"
    try:
        if draw.textlength(t, font=font) <= max_width:
            return t
    except Exception:
        return t[:60]
    # Truncate with ellipsis
    while len(t) > 4:
        t = t[:-1]
        try:
            if draw.textlength(t + "…", font=font) <= max_width:
                return t + "…"
        except Exception:
            return t[:40] + "…"
    return t


def _draw_subtle_grid(draw: Any, width: int, height: int) -> None:
    """Faint technical grid — premium poster atmosphere, not clutter."""
    step = max(48, width // 24)
    grid = (18, 36, 68)
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill=grid, width=1)
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=grid, width=1)


def render_abstract_frame(
    *,
    width: int = _W,
    height: int = _H,
    variant: int = 0,
    watermark: str = "Mira",
) -> Any:
    """Cinematic gradient still — no topic text, tiny corner mark only."""
    from PIL import Image, ImageDraw, ImageFilter

    pal = _ABSTRACT_PALETTES[int(variant) % len(_ABSTRACT_PALETTES)]
    top, mid, bot = pal
    img = Image.new("RGB", (width, height), top)
    _draw_gradient(img, top, bot)

    # Soft mid-glow (atmosphere, not a creature spotlight)
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx = int(width * (0.35 + 0.15 * (variant % 3)))
    cy = int(height * (0.40 + 0.08 * ((variant + 1) % 3)))
    rx, ry = int(width * 0.38), int(height * 0.32)
    gdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=mid)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(50, width // 12)))
    img = Image.blend(img, glow, 0.35)

    # Soft abstract shapes (no icons, no faces)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(3):
        ox = int(width * (0.15 + 0.25 * ((variant + k) % 4)))
        oy = int(height * (0.2 + 0.2 * k))
        r = int(min(width, height) * (0.08 + 0.04 * k))
        col = (*_lerp(mid, bot, 0.3 + 0.2 * k), 55)
        od.ellipse([ox - r, oy - r, ox + r, oy + r], fill=col)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=max(20, width // 40)))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Tiny corner mark only — never the user prompt
    mark = (watermark or "Mira").strip()[:8] or "Mira"
    font_mark = _load_font(max(14, height // 40), bold=False)
    pad = int(width * 0.04)
    try:
        mw = draw.textlength(mark, font=font_mark)
    except Exception:
        mw = len(mark) * 8
    draw.text(
        (width - pad - int(mw), height - int(height * 0.06)),
        mark,
        font=font_mark,
        fill=(255, 255, 255, 90) if False else (200, 210, 220),
    )
    # Soft VERIDIQ watermark (very subtle, not a title)
    font_vq = _load_font(max(12, height // 48), bold=False)
    draw.text((pad, height - int(height * 0.06)), "VERIDIQ", font=font_vq, fill=_MUTED)

    return img


def _draw_kitchen_bg(img: Any, width: int, height: int) -> None:
    """Cozy kitchen backdrop — wood counter, window light, shelves; no bare voids."""
    from PIL import Image, ImageDraw, ImageFilter

    # Warm wall: soft sky-blue → peach (never flat off-white)
    _draw_gradient(img, (168, 198, 228), (255, 220, 185))
    draw = ImageDraw.Draw(img)

    # Soft ambient wash (warm mid-tone — kills beige void feel)
    wash = Image.new("RGB", (width, height), (0, 0, 0))
    wdraw = ImageDraw.Draw(wash)
    wdraw.ellipse(
        [
            int(width * 0.10),
            int(height * 0.02),
            int(width * 0.90),
            int(height * 0.72),
        ],
        fill=(255, 228, 190),
    )
    wash = wash.filter(ImageFilter.GaussianBlur(radius=max(40, width // 16)))
    img_blend = Image.blend(img, wash, 0.38)
    img.paste(img_blend)

    draw = ImageDraw.Draw(img)

    # Wall tone band above counter (plaster with warm bias)
    wall_bot = int(height * 0.72)
    for y in range(0, wall_bot):
        t = y / max(1, wall_bot - 1)
        c = _lerp((175, 205, 232), (252, 224, 188), t)
        draw.line([(0, y), (width, y)], fill=c)

    # Soft wall texture mottling (breaks empty flat plaster)
    mott = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    md = ImageDraw.Draw(mott)
    for i in range(18):
        mx = int(width * ((0.12 * i + 0.07) % 0.95))
        my = int(height * ((0.09 * i + 0.11) % 0.65))
        mr = int(min(width, height) * (0.04 + 0.02 * (i % 3)))
        md.ellipse(
            [mx - mr, my - mr, mx + mr, my + mr],
            fill=(255, 240, 210, 18 + (i % 5)),
        )
    mott = mott.filter(ImageFilter.GaussianBlur(radius=max(16, width // 50)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), mott).convert("RGB"))
    draw = ImageDraw.Draw(img)

    # Window with outdoor view (NOT empty white rectangle)
    wx0, wy0 = int(width * 0.06), int(height * 0.10)
    wx1, wy1 = int(width * 0.32), int(height * 0.50)
    # Frame
    draw.rounded_rectangle(
        [wx0 - 8, wy0 - 8, wx1 + 8, wy1 + 10],
        radius=8,
        fill=(150, 115, 75),
        outline=(100, 70, 45),
        width=3,
    )
    # Outdoor sky→hills gradient inside panes
    for y in range(wy0, wy1):
        t = (y - wy0) / max(1, wy1 - wy0)
        if t < 0.50:
            c = _lerp((110, 175, 235), (185, 215, 245), t / 0.50)
        else:
            c = _lerp((100, 155, 85), (70, 120, 65), (t - 0.50) / 0.50)
        draw.line([(wx0, y), (wx1, y)], fill=c)
    # Soft sun disc
    sx = int((wx0 + wx1) * 0.65)
    sy = int(wy0 + (wy1 - wy0) * 0.28)
    sr = max(12, int(min(width, height) * 0.04))
    draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 235, 150))
    # Distant tree silhouettes in window
    for txf, thf in ((0.22, 0.18), (0.38, 0.14), (0.78, 0.16)):
        tx = int(wx0 + (wx1 - wx0) * txf)
        th = int((wy1 - wy0) * thf)
        base = int(wy0 + (wy1 - wy0) * 0.72)
        draw.polygon(
            [(tx, base - th), (tx - int(width * 0.018), base), (tx + int(width * 0.018), base)],
            fill=(55, 100, 55),
        )
    # Window muntins
    mx = (wx0 + wx1) // 2
    my = (wy0 + wy1) // 2
    draw.line([(mx, wy0), (mx, wy1)], fill=(140, 105, 70), width=max(3, width // 320))
    draw.line([(wx0, my), (wx1, my)], fill=(140, 105, 70), width=max(3, width // 320))
    # Inner sill with tiny plant pot
    draw.rectangle([wx0 - 6, wy1, wx1 + 6, wy1 + max(8, height // 70)], fill=(175, 140, 95))
    pot_x = int(wx0 + (wx1 - wx0) * 0.78)
    draw.rectangle(
        [pot_x - 8, wy1 - max(14, height // 45), pot_x + 8, wy1],
        fill=(180, 90, 70),
    )
    draw.ellipse(
        [pot_x - 10, wy1 - max(28, height // 28), pot_x + 10, wy1 - max(10, height // 55)],
        fill=(50, 130, 70),
    )

    # Soft light rays from window (warm translucent wedges)
    rays = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for i, (x_off, alpha) in enumerate(((0.10, 42), (0.22, 30), (0.36, 20))):
        tip_x = int(wx1 + width * x_off)
        tip_y = int(height * (0.52 + 0.06 * i))
        rd.polygon(
            [(wx1 - 4, wy0 + 8), (wx1 - 4, wy1 - 8), (tip_x, tip_y)],
            fill=(255, 242, 200, alpha),
        )
    rays = rays.filter(ImageFilter.GaussianBlur(radius=max(14, width // 70)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), rays).convert("RGB"))
    draw = ImageDraw.Draw(img)

    # Upper shelf with jar / plate silhouettes
    shelf_y = int(height * 0.14)
    shelf_x0, shelf_x1 = int(width * 0.52), int(width * 0.95)
    draw.rectangle(
        [shelf_x0, shelf_y, shelf_x1, shelf_y + max(6, height // 90)],
        fill=(145, 108, 68),
    )
    draw.rectangle(
        [shelf_x0, shelf_y + max(6, height // 90), shelf_x1, shelf_y + max(10, height // 60)],
        fill=(110, 80, 48),
    )
    # Jars
    for i, jx in enumerate((0.58, 0.70, 0.82)):
        jcx = int(width * jx)
        jw = int(width * 0.038)
        jh = int(height * 0.08)
        top = shelf_y - jh
        fill = ((210, 115, 85), (165, 195, 215), (220, 185, 95))[i % 3]
        draw.rounded_rectangle(
            [jcx - jw, top, jcx + jw, shelf_y],
            radius=5,
            fill=fill,
            outline=(100, 80, 60),
            width=2,
        )
        draw.rectangle(
            [jcx - jw // 2, top - max(5, height // 80), jcx + jw // 2, top],
            fill=(120, 90, 60),
        )
    # Plate leaning
    px = int(width * 0.91)
    pr = int(min(width, height) * 0.03)
    draw.ellipse(
        [px - pr, shelf_y - pr * 2 - 2, px + pr, shelf_y - 2],
        fill=(245, 238, 225),
        outline=(170, 155, 140),
        width=2,
    )

    # Second lower shelf
    shelf2 = int(height * 0.34)
    draw.rectangle(
        [shelf_x0 + int(width * 0.05), shelf2, shelf_x1, shelf2 + max(5, height // 100)],
        fill=(140, 105, 68),
    )
    for i, jx in enumerate((0.66, 0.78, 0.88)):
        jcx = int(width * jx)
        jw = int(width * 0.03)
        jh = int(height * 0.06)
        fill = ((155, 135, 115), (200, 95, 85), (90, 140, 160))[i % 3]
        draw.rounded_rectangle(
            [jcx - jw, shelf2 - jh, jcx + jw, shelf2],
            radius=3,
            fill=fill,
            outline=(95, 75, 55),
            width=1,
        )

    # Backsplash hint (subtle tile band above counter)
    splash_top = int(height * 0.62)
    for y in range(splash_top, int(height * 0.76)):
        draw.line([(0, y), (width, y)], fill=_lerp((235, 215, 195), (220, 200, 180), (y - splash_top) / max(1, int(height * 0.14))))
    # Faint tile grid
    for i in range(10):
        x = int(width * (0.05 + i * 0.1))
        draw.line([(x, splash_top), (x, int(height * 0.76))], fill=(210, 190, 170), width=1)

    # Wood counter (warm grain, not flat beige strip)
    table_y = int(height * 0.76)
    for y in range(table_y, height):
        t = (y - table_y) / max(1, height - table_y)
        c = _lerp((195, 148, 95), (125, 85, 50), t)
        draw.line([(0, y), (width, y)], fill=c)
    # Counter edge highlight
    draw.rectangle(
        [0, table_y, width, table_y + max(6, height // 70)],
        fill=(220, 175, 120),
    )
    draw.rectangle(
        [0, table_y + max(6, height // 70), width, table_y + max(10, height // 48)],
        fill=(110, 75, 42),
    )
    # Subtle wood grain lines
    for i in range(7):
        gy = table_y + max(16, height // 36) + i * max(10, height // 50)
        if gy >= height - 4:
            break
        draw.line(
            [(int(width * 0.02), gy), (int(width * 0.98), gy + (i % 3) - 1)],
            fill=(155, 110, 70),
            width=1,
        )

    # Soft vignette (gentle — keeps fruit readable)
    _apply_soft_vignette(img, strength=0.26)


def _apply_soft_vignette(img: Any, *, strength: float = 0.25) -> None:
    """Darken edges slightly for depth; mutates img in place."""
    from PIL import Image, ImageDraw, ImageFilter

    try:
        w, h = img.size
        vig = Image.new("L", (w, h), 0)
        vd = ImageDraw.Draw(vig)
        margin = int(min(w, h) * 0.08)
        vd.ellipse(
            [margin, margin, w - margin, h - margin],
            fill=int(255 * (1.0 - max(0.05, min(0.45, strength)))),
        )
        vig = vig.filter(ImageFilter.GaussianBlur(radius=max(40, w // 14)))
        # Brighten center relative to edges via multiply-ish composite
        black = Image.new("RGB", (w, h), (0, 0, 0))
        # Invert mask logic: high = keep original, low = darken
        mask = vig.point(lambda p: max(0, min(255, int(p + (255 - p) * (1.0 - strength)))))
        blended = Image.composite(img, black, mask)
        # Soft mix so vignette isn't harsh
        out = Image.blend(img, blended, strength)
        img.paste(out)
    except Exception:
        pass


def detect_illustration_subject(topic: str) -> str:
    """Parse a simple drawable subject keyword from the topic (or 'scenic')."""
    t = (topic or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    for kw, kind in _ILLUSTRATION_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", t):
            return kind
    return "scenic"


def _theme_for_subject(kind: str) -> str:
    """Background theme name for a subject kind."""
    k = (kind or "scenic").lower()
    return {
        "dog": "park",
        "cat": "park",
        "bird": "park",
        "fox": "forest",
        "bear": "forest",
        "lion": "savanna",
        "horse": "park",
        "dragon": "dusk",
        "car": "road",
        "train": "road",
        "plane": "sky",
        "boat": "beach",
        "beach": "beach",
        "mountain": "mountain",
        "forest": "forest",
        "house": "suburb",
        "gym": "gym",
        "robot": "tech",
        "rocket": "space",
        "person": "park",
        "scenic": "hills",
    }.get(k, "hills")


def _draw_scenic_bg(img: Any, width: int, height: int, *, theme: str = "hills", variant: int = 0) -> None:
    """Rich scenic gradient + ground plane + soft decor (no topic text)."""
    from PIL import Image, ImageDraw, ImageFilter

    theme_l = (theme or "hills").lower()
    pals = {
        "hills": ((110, 170, 220), (200, 225, 245), (70, 130, 70), (50, 100, 55)),
        "park": ((130, 190, 235), (210, 235, 250), (80, 150, 70), (55, 110, 50)),
        "forest": ((70, 110, 90), (140, 170, 130), (40, 80, 45), (30, 60, 35)),
        "beach": ((120, 190, 235), (255, 230, 180), (70, 160, 190), (230, 210, 150)),
        "mountain": ((90, 130, 180), (200, 210, 230), (90, 100, 110), (60, 70, 80)),
        "road": ((100, 150, 200), (180, 200, 220), (70, 75, 80), (45, 48, 52)),
        "gym": ((40, 45, 55), (70, 75, 90), (50, 50, 55), (30, 30, 35)),
        "tech": ((20, 40, 70), (40, 80, 120), (30, 50, 80), (15, 30, 50)),
        "space": ((8, 10, 30), (30, 20, 60), (15, 15, 35), (5, 5, 20)),
        "dusk": ((40, 30, 70), (180, 90, 70), (60, 40, 50), (30, 20, 35)),
        "savanna": ((200, 170, 90), (240, 210, 140), (180, 140, 70), (140, 110, 50)),
        "suburb": ((140, 190, 230), (220, 235, 245), (90, 140, 80), (70, 110, 60)),
        "sky": ((90, 160, 230), (200, 220, 245), (160, 190, 220), (120, 160, 200)),
    }
    sky_top, sky_bot, ground_top, ground_bot = pals.get(theme_l, pals["hills"])
    # Shift palette slightly by variant
    shift = (variant % 3) * 8
    sky_top = tuple(max(0, min(255, c + (shift if i == 2 else -shift // 2))) for i, c in enumerate(sky_top))  # type: ignore[assignment]
    _draw_gradient(img, sky_top, sky_bot)  # type: ignore[arg-type]
    draw = ImageDraw.Draw(img)

    ground_y = int(height * (0.62 if theme_l not in ("sky", "space") else 0.85))
    for y in range(ground_y, height):
        t = (y - ground_y) / max(1, height - ground_y)
        c = _lerp(ground_top, ground_bot, t)  # type: ignore[arg-type]
        draw.line([(0, y), (width, y)], fill=c)

    # Soft sun / moon
    if theme_l == "space":
        # Stars
        for i in range(28):
            sx = int(width * ((0.07 * i + 0.11 * (variant + i)) % 0.95))
            sy = int(height * ((0.05 * i + 0.09 * variant) % 0.55))
            r = 1 + (i % 3)
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(220, 220, 255))
        # Planet
        px, py, pr = int(width * 0.78), int(height * 0.22), int(min(width, height) * 0.08)
        draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(180, 120, 200))
    elif theme_l != "gym":
        sun_x = int(width * (0.78 + 0.04 * (variant % 2)))
        sun_y = int(height * 0.18)
        sr = int(min(width, height) * (0.06 if theme_l != "dusk" else 0.08))
        scol = (255, 220, 120) if theme_l != "dusk" else (255, 140, 80)
        draw.ellipse([sun_x - sr, sun_y - sr, sun_x + sr, sun_y + sr], fill=scol)

    # Silhouette hills / decor
    if theme_l in ("hills", "park", "suburb", "forest", "savanna", "mountain", "dusk"):
        hill = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hill)
        base = ground_y + 4
        col = (*ground_bot[:3], 180) if len(ground_bot) == 3 else (40, 70, 40, 180)
        # Far hills
        hd.polygon(
            [
                (0, base),
                (int(width * 0.15), int(base - height * 0.12)),
                (int(width * 0.35), int(base - height * 0.06)),
                (int(width * 0.55), int(base - height * 0.16)),
                (int(width * 0.75), int(base - height * 0.05)),
                (width, int(base - height * 0.10)),
                (width, height),
                (0, height),
            ],
            fill=col,
        )
        img_rgba = Image.alpha_composite(img.convert("RGBA"), hill).convert("RGB")
        img.paste(img_rgba)
        draw = ImageDraw.Draw(img)

    if theme_l == "road":
        # Road surface already from ground; add dashed center line
        mid = ground_y + (height - ground_y) // 3
        for i in range(8):
            x0 = int(width * (0.05 + i * 0.12))
            draw.rectangle(
                [x0, mid, x0 + int(width * 0.06), mid + max(3, height // 90)],
                fill=(220, 200, 80),
            )
        # Distant buildings
        for i, (bx, bh) in enumerate(((0.08, 0.22), (0.18, 0.30), (0.28, 0.18))):
            x0 = int(width * bx)
            y0 = ground_y - int(height * bh)
            draw.rectangle([x0, y0, x0 + int(width * 0.07), ground_y], fill=(90, 100, 120))

    if theme_l == "beach":
        # Water band
        wy = int(height * 0.58)
        for y in range(wy, ground_y):
            t = (y - wy) / max(1, ground_y - wy)
            c = _lerp((70, 160, 200), (100, 190, 210), t)
            draw.line([(0, y), (width, y)], fill=c)

    if theme_l == "gym":
        # Floor mats + wall mirrors hint
        draw.rectangle([0, ground_y, width, height], fill=(45, 45, 50))
        for i in range(4):
            x0 = int(width * (0.1 + i * 0.22))
            draw.rectangle(
                [x0, ground_y + 8, x0 + int(width * 0.16), height - 8],
                fill=(55, 55, 62),
                outline=(70, 70, 80),
                width=1,
            )
        # Window light strip
        draw.rectangle(
            [int(width * 0.7), int(height * 0.1), int(width * 0.92), int(height * 0.45)],
            fill=(80, 95, 110),
            outline=(100, 120, 140),
            width=2,
        )

    if theme_l == "tech":
        # Soft circuit glow orbs
        glow = Image.new("RGB", (width, height), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse(
            [int(width * 0.55), int(height * 0.1), int(width * 0.95), int(height * 0.55)],
            fill=(40, 120, 200),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(40, width // 16)))
        img.paste(Image.blend(img, glow, 0.25))
        draw = ImageDraw.Draw(img)
        # Floor grid
        for i in range(6):
            y = ground_y + i * max(12, height // 40)
            draw.line([(0, y), (width, y)], fill=(40, 70, 100), width=1)

    # Soft ground shadow oval (fruit/subject sits on this)
    sh_cx, sh_cy = width // 2, int(height * 0.78)
    sh_rx, sh_ry = int(width * 0.18), int(height * 0.04)
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse(
        [sh_cx - sh_rx, sh_cy - sh_ry, sh_cx + sh_rx, sh_cy + sh_ry],
        fill=(0, 0, 0, 55),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(8, width // 100)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB"))

    _apply_soft_vignette(img, strength=0.20)


def _draw_subject_face(
    draw: Any,
    cx: int,
    cy: int,
    scale: float,
    *,
    mouth_open: bool = False,
) -> None:
    """Reuse cute face for local illustration characters."""
    _draw_cute_face(draw, cx, cy, scale, mouth_open=mouth_open)


def _draw_illustration_subject(
    draw: Any,
    kind: str,
    *,
    cx: int,
    cy: int,
    scale: float,
    mouth_open: bool = False,
) -> None:
    """Draw a simple clear centered subject (emoji-free shapes)."""
    k = (kind or "scenic").lower()

    if k == "dog":
        body = (180, 120, 70)
        ear = (150, 95, 55)
        r = int(110 * scale)
        # Soft under-shadow already on bg; body
        draw.ellipse([cx - r, cy - int(r * 0.85), cx + r, cy + int(r * 0.95)], fill=body)
        # Ears
        for sign in (-1, 1):
            ex = cx + sign * int(85 * scale)
            ey = cy - int(90 * scale)
            draw.ellipse(
                [ex - int(35 * scale), ey - int(55 * scale), ex + int(35 * scale), ey + int(25 * scale)],
                fill=ear,
            )
        # Snout
        draw.ellipse(
            [cx - int(45 * scale), cy + int(10 * scale), cx + int(45 * scale), cy + int(70 * scale)],
            fill=(230, 200, 170),
        )
        draw.ellipse(
            [cx - int(12 * scale), cy + int(35 * scale), cx + int(12 * scale), cy + int(55 * scale)],
            fill=(40, 30, 25),
        )
        _draw_subject_face(draw, cx, cy - int(15 * scale), scale * 0.95, mouth_open=mouth_open)
        return

    if k == "cat":
        body = (220, 160, 90)
        r = int(100 * scale)
        draw.ellipse([cx - r, cy - int(r * 0.9), cx + r, cy + int(r * 0.9)], fill=body)
        # Pointy ears
        for sign in (-1, 1):
            tip = (cx + sign * int(70 * scale), cy - int(140 * scale))
            draw.polygon(
                [
                    (cx + sign * int(30 * scale), cy - int(70 * scale)),
                    tip,
                    (cx + sign * int(95 * scale), cy - int(50 * scale)),
                ],
                fill=body,
            )
        _draw_subject_face(draw, cx, cy, scale * 0.9, mouth_open=mouth_open)
        # Whiskers
        for sign in (-1, 1):
            wy = cy + int(20 * scale)
            draw.line(
                [(cx + sign * int(20 * scale), wy), (cx + sign * int(90 * scale), wy - int(8 * scale))],
                fill=(80, 60, 40),
                width=max(1, int(2 * scale)),
            )
        return

    if k == "bird":
        body = (70, 150, 210)
        r = int(90 * scale)
        draw.ellipse([cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.9)], fill=body)
        # Beak
        draw.polygon(
            [
                (cx + int(70 * scale), cy),
                (cx + int(130 * scale), cy + int(10 * scale)),
                (cx + int(70 * scale), cy + int(28 * scale)),
            ],
            fill=(240, 170, 40),
        )
        # Wing
        draw.ellipse(
            [cx - int(40 * scale), cy, cx + int(50 * scale), cy + int(70 * scale)],
            fill=(50, 120, 180),
        )
        _draw_subject_face(draw, cx - int(10 * scale), cy - int(10 * scale), scale * 0.75, mouth_open=mouth_open)
        return

    if k == "robot":
        body = (160, 175, 195)
        # Head
        hw, hh = int(90 * scale), int(80 * scale)
        draw.rounded_rectangle(
            [cx - hw, cy - hh - int(40 * scale), cx + hw, cy - int(10 * scale)],
            radius=12,
            fill=body,
            outline=(80, 90, 110),
            width=max(2, int(3 * scale)),
        )
        # Antenna
        draw.line(
            [(cx, cy - hh - int(40 * scale)), (cx, cy - hh - int(75 * scale))],
            fill=(80, 90, 110),
            width=max(2, int(3 * scale)),
        )
        draw.ellipse(
            [cx - int(10 * scale), cy - hh - int(90 * scale), cx + int(10 * scale), cy - hh - int(70 * scale)],
            fill=(255, 90, 90),
        )
        # Body
        draw.rounded_rectangle(
            [cx - int(70 * scale), cy - int(5 * scale), cx + int(70 * scale), cy + int(110 * scale)],
            radius=10,
            fill=(120, 140, 170),
            outline=(70, 80, 100),
            width=max(2, int(2 * scale)),
        )
        # Chest panel
        draw.rectangle(
            [cx - int(35 * scale), cy + int(20 * scale), cx + int(35 * scale), cy + int(55 * scale)],
            fill=(60, 200, 220),
        )
        _draw_subject_face(draw, cx, cy - int(50 * scale), scale * 0.85, mouth_open=mouth_open)
        return

    if k == "car":
        body = (220, 70, 70)
        # Cabin
        draw.polygon(
            [
                (cx - int(70 * scale), cy - int(20 * scale)),
                (cx - int(30 * scale), cy - int(80 * scale)),
                (cx + int(50 * scale), cy - int(80 * scale)),
                (cx + int(100 * scale), cy - int(20 * scale)),
            ],
            fill=(180, 210, 230),
        )
        # Body
        draw.rounded_rectangle(
            [cx - int(130 * scale), cy - int(25 * scale), cx + int(130 * scale), cy + int(45 * scale)],
            radius=18,
            fill=body,
            outline=(140, 40, 40),
            width=max(2, int(3 * scale)),
        )
        # Wheels
        for sign in (-1, 1):
            wx = cx + sign * int(75 * scale)
            wy = cy + int(50 * scale)
            wr = int(32 * scale)
            draw.ellipse([wx - wr, wy - wr, wx + wr, wy + wr], fill=(40, 40, 45))
            draw.ellipse(
                [wx - wr // 2, wy - wr // 2, wx + wr // 2, wy + wr // 2],
                fill=(160, 160, 170),
            )
        # Headlight
        draw.ellipse(
            [cx + int(100 * scale), cy - int(5 * scale), cx + int(125 * scale), cy + int(20 * scale)],
            fill=(255, 240, 160),
        )
        return

    if k == "gym":
        # Simple athlete + dumbbell silhouette
        skin = (230, 180, 140)
        shirt = (50, 140, 220)
        # Head
        hr = int(40 * scale)
        draw.ellipse([cx - hr, cy - int(130 * scale), cx + hr, cy - int(50 * scale)], fill=skin)
        # Torso
        draw.rounded_rectangle(
            [cx - int(45 * scale), cy - int(50 * scale), cx + int(45 * scale), cy + int(50 * scale)],
            radius=8,
            fill=shirt,
        )
        # Arms + dumbbell
        draw.line(
            [(cx - int(45 * scale), cy - int(20 * scale)), (cx - int(120 * scale), cy + int(10 * scale))],
            fill=skin,
            width=max(8, int(14 * scale)),
        )
        draw.line(
            [(cx + int(45 * scale), cy - int(20 * scale)), (cx + int(120 * scale), cy + int(10 * scale))],
            fill=skin,
            width=max(8, int(14 * scale)),
        )
        for sign in (-1, 1):
            bx = cx + sign * int(130 * scale)
            by = cy + int(10 * scale)
            draw.rectangle(
                [bx - int(18 * scale), by - int(28 * scale), bx + int(18 * scale), by + int(28 * scale)],
                fill=(60, 60, 70),
            )
        draw.line(
            [(cx - int(130 * scale), cy + int(10 * scale)), (cx + int(130 * scale), cy + int(10 * scale))],
            fill=(80, 80, 90),
            width=max(4, int(6 * scale)),
        )
        # Legs
        draw.rectangle(
            [cx - int(35 * scale), cy + int(50 * scale), cx - int(8 * scale), cy + int(130 * scale)],
            fill=(40, 40, 55),
        )
        draw.rectangle(
            [cx + int(8 * scale), cy + int(50 * scale), cx + int(35 * scale), cy + int(130 * scale)],
            fill=(40, 40, 55),
        )
        _draw_subject_face(draw, cx, cy - int(90 * scale), scale * 0.7, mouth_open=mouth_open)
        return

    if k == "dragon":
        body = (60, 160, 90)
        r = int(110 * scale)
        draw.ellipse([cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.9)], fill=body)
        # Wings
        for sign in (-1, 1):
            draw.polygon(
                [
                    (cx + sign * int(40 * scale), cy - int(20 * scale)),
                    (cx + sign * int(160 * scale), cy - int(100 * scale)),
                    (cx + sign * int(90 * scale), cy + int(30 * scale)),
                ],
                fill=(40, 120, 70),
            )
        # Horns
        for sign in (-1, 1):
            draw.polygon(
                [
                    (cx + sign * int(25 * scale), cy - int(70 * scale)),
                    (cx + sign * int(45 * scale), cy - int(130 * scale)),
                    (cx + sign * int(55 * scale), cy - int(60 * scale)),
                ],
                fill=(200, 200, 210),
            )
        _draw_subject_face(draw, cx, cy - int(10 * scale), scale * 0.95, mouth_open=mouth_open)
        return

    if k == "rocket":
        body = (220, 220, 230)
        # Nose
        draw.polygon(
            [
                (cx, cy - int(140 * scale)),
                (cx - int(45 * scale), cy - int(40 * scale)),
                (cx + int(45 * scale), cy - int(40 * scale)),
            ],
            fill=(220, 70, 70),
        )
        draw.rounded_rectangle(
            [cx - int(45 * scale), cy - int(40 * scale), cx + int(45 * scale), cy + int(90 * scale)],
            radius=8,
            fill=body,
            outline=(100, 100, 120),
            width=2,
        )
        # Window
        wr = int(22 * scale)
        draw.ellipse([cx - wr, cy - int(10 * scale), cx + wr, cy + int(35 * scale)], fill=(100, 180, 230))
        # Fins
        for sign in (-1, 1):
            draw.polygon(
                [
                    (cx + sign * int(45 * scale), cy + int(40 * scale)),
                    (cx + sign * int(95 * scale), cy + int(100 * scale)),
                    (cx + sign * int(45 * scale), cy + int(90 * scale)),
                ],
                fill=(220, 70, 70),
            )
        # Flame
        draw.polygon(
            [
                (cx - int(25 * scale), cy + int(90 * scale)),
                (cx, cy + int(150 * scale)),
                (cx + int(25 * scale), cy + int(90 * scale)),
            ],
            fill=(255, 160, 40),
        )
        return

    if k == "house":
        # Simple house
        draw.rectangle(
            [cx - int(100 * scale), cy - int(20 * scale), cx + int(100 * scale), cy + int(100 * scale)],
            fill=(230, 200, 160),
            outline=(140, 110, 80),
            width=2,
        )
        draw.polygon(
            [
                (cx - int(120 * scale), cy - int(20 * scale)),
                (cx, cy - int(110 * scale)),
                (cx + int(120 * scale), cy - int(20 * scale)),
            ],
            fill=(180, 70, 60),
        )
        draw.rectangle(
            [cx - int(25 * scale), cy + int(20 * scale), cx + int(25 * scale), cy + int(100 * scale)],
            fill=(120, 80, 50),
        )
        draw.rectangle(
            [cx - int(75 * scale), cy + int(10 * scale), cx - int(40 * scale), cy + int(45 * scale)],
            fill=(140, 200, 230),
        )
        return

    if k in ("boat", "train", "plane", "beach", "mountain", "forest", "scenic"):
        # Generic hero shape: rounded emblem + optional face for speak
        if k == "boat":
            draw.polygon(
                [
                    (cx - int(120 * scale), cy + int(20 * scale)),
                    (cx + int(120 * scale), cy + int(20 * scale)),
                    (cx + int(80 * scale), cy + int(70 * scale)),
                    (cx - int(80 * scale), cy + int(70 * scale)),
                ],
                fill=(180, 90, 60),
            )
            draw.polygon(
                [
                    (cx - int(10 * scale), cy + int(15 * scale)),
                    (cx - int(10 * scale), cy - int(100 * scale)),
                    (cx + int(80 * scale), cy + int(15 * scale)),
                ],
                fill=(240, 240, 245),
            )
            return
        if k == "plane":
            draw.ellipse(
                [cx - int(120 * scale), cy - int(25 * scale), cx + int(120 * scale), cy + int(25 * scale)],
                fill=(220, 225, 235),
            )
            draw.ellipse(
                [cx - int(20 * scale), cy - int(70 * scale), cx + int(20 * scale), cy + int(70 * scale)],
                fill=(200, 205, 220),
            )
            return
        if k == "train":
            draw.rounded_rectangle(
                [cx - int(110 * scale), cy - int(50 * scale), cx + int(110 * scale), cy + int(60 * scale)],
                radius=12,
                fill=(60, 120, 200),
            )
            draw.rectangle(
                [cx + int(40 * scale), cy - int(90 * scale), cx + int(80 * scale), cy - int(50 * scale)],
                fill=(60, 120, 200),
            )
            for sign in (-1, 0, 1):
                wx = cx + sign * int(55 * scale)
                draw.ellipse(
                    [wx - int(22 * scale), cy + int(45 * scale), wx + int(22 * scale), cy + int(90 * scale)],
                    fill=(40, 40, 45),
                )
            return
        if k == "mountain":
            draw.polygon(
                [
                    (cx - int(140 * scale), cy + int(80 * scale)),
                    (cx - int(40 * scale), cy - int(100 * scale)),
                    (cx + int(40 * scale), cy + int(20 * scale)),
                    (cx + int(140 * scale), cy + int(80 * scale)),
                ],
                fill=(110, 120, 130),
            )
            draw.polygon(
                [
                    (cx - int(55 * scale), cy - int(70 * scale)),
                    (cx - int(40 * scale), cy - int(100 * scale)),
                    (cx - int(10 * scale), cy - int(50 * scale)),
                ],
                fill=(240, 245, 250),
            )
            return
        if k == "forest":
            for i, (ox, hmul, col) in enumerate(
                (
                    (-70, 1.1, (40, 100, 50)),
                    (0, 1.3, (50, 130, 60)),
                    (70, 1.0, (35, 90, 45)),
                )
            ):
                tx = cx + int(ox * scale)
                th = int(120 * hmul * scale)
                draw.rectangle(
                    [tx - int(10 * scale), cy + int(40 * scale), tx + int(10 * scale), cy + int(90 * scale)],
                    fill=(90, 60, 30),
                )
                draw.polygon(
                    [
                        (tx, cy - th),
                        (tx - int(55 * scale), cy + int(50 * scale)),
                        (tx + int(55 * scale), cy + int(50 * scale)),
                    ],
                    fill=col,
                )
            return
        if k == "beach":
            # Palm + sun already in bg — draw a simple umbrella
            draw.line(
                [(cx, cy + int(80 * scale)), (cx, cy - int(40 * scale))],
                fill=(140, 100, 60),
                width=max(4, int(6 * scale)),
            )
            draw.pieslice(
                [cx - int(90 * scale), cy - int(100 * scale), cx + int(90 * scale), cy + int(20 * scale)],
                start=200,
                end=340,
                fill=(230, 80, 70),
            )
            return

    if k == "person":
        skin = (230, 180, 140)
        shirt = (70, 130, 200)
        hr = int(48 * scale)
        draw.ellipse(
            [cx - hr, cy - int(120 * scale), cx + hr, cy - int(25 * scale)],
            fill=skin,
        )
        draw.rounded_rectangle(
            [cx - int(55 * scale), cy - int(25 * scale), cx + int(55 * scale), cy + int(70 * scale)],
            radius=10,
            fill=shirt,
        )
        draw.rectangle(
            [cx - int(40 * scale), cy + int(70 * scale), cx - int(10 * scale), cy + int(140 * scale)],
            fill=(50, 55, 70),
        )
        draw.rectangle(
            [cx + int(10 * scale), cy + int(70 * scale), cx + int(40 * scale), cy + int(140 * scale)],
            fill=(50, 55, 70),
        )
        _draw_subject_face(draw, cx, cy - int(70 * scale), scale * 0.75, mouth_open=mouth_open)
        return

    if k in ("lion", "bear", "fox", "horse"):
        colors = {
            "lion": (210, 160, 60),
            "bear": (120, 80, 45),
            "fox": (220, 120, 50),
            "horse": (140, 100, 70),
        }
        body = colors.get(k, (160, 120, 80))
        r = int(105 * scale)
        draw.ellipse([cx - r, cy - int(r * 0.85), cx + r, cy + int(r * 0.9)], fill=body)
        if k == "lion":
            # Mane ring
            draw.ellipse(
                [cx - int(r * 1.25), cy - int(r * 1.15), cx + int(r * 1.25), cy + int(r * 0.5)],
                outline=(180, 120, 40),
                width=max(8, int(16 * scale)),
            )
        if k == "fox":
            for sign in (-1, 1):
                draw.polygon(
                    [
                        (cx + sign * int(35 * scale), cy - int(60 * scale)),
                        (cx + sign * int(70 * scale), cy - int(130 * scale)),
                        (cx + sign * int(90 * scale), cy - int(40 * scale)),
                    ],
                    fill=body,
                )
        _draw_subject_face(draw, cx, cy, scale * 0.9, mouth_open=mouth_open)
        return

    # Default scenic: soft rounded hero orb (no topic text)
    r = int(100 * scale)
    fill = (90, 160, 200)
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=fill,
        outline=(50, 100, 140),
        width=max(2, int(3 * scale)),
    )
    hi = int(40 * scale)
    draw.ellipse(
        [cx - int(50 * scale), cy - int(55 * scale), cx - int(50 * scale) + hi, cy - int(55 * scale) + hi],
        fill=(180, 220, 240),
    )


def render_topic_illustration(
    topic: str = "",
    *,
    subject: str | None = None,
    mouth_open: bool = False,
    width: int = _W,
    height: int = _H,
    variant: int = 0,
) -> Any:
    """Topic-aware local illustration — clear centered subject on rich scenic bg.

    Never paints topic text. Prefer this over abstract color pads when AI fails.
    """
    from PIL import Image, ImageDraw, ImageFilter

    kind = (subject or detect_illustration_subject(topic) or "scenic").lower()
    theme = _theme_for_subject(kind)
    W, H = int(width), int(height)
    img = Image.new("RGB", (W, H), (100, 150, 200))
    _draw_scenic_bg(img, W, H, theme=theme, variant=variant)
    draw = ImageDraw.Draw(img)

    cx, cy = W // 2, int(H * 0.48)
    scale = min(W, H) / 720.0

    # Soft contact shadow under subject
    sh_rx, sh_ry = int(140 * scale), int(28 * scale)
    shy = int(H * 0.76)
    draw.ellipse(
        [cx - sh_rx, shy - sh_ry, cx + sh_rx, shy + sh_ry],
        fill=(40, 50, 40) if theme not in ("gym", "tech", "space") else (20, 20, 25),
    )

    use_mouth = bool(mouth_open) and kind in _FACE_SUBJECTS
    if kind != "scenic" or detect_illustration_subject(topic) != "scenic":
        _draw_illustration_subject(
            draw, kind, cx=cx, cy=cy, scale=scale, mouth_open=use_mouth
        )
    else:
        # Scenic-only: hills already drawn; add a soft focal orb so frame isn't empty
        _draw_illustration_subject(
            draw, "scenic", cx=cx, cy=cy, scale=scale * 0.85, mouth_open=False
        )

    # Tiny Mira mark — never topic text
    font_mark = _load_font(max(14, H // 40), bold=False)
    draw.text((int(W * 0.04), H - int(H * 0.06)), "Mira", font=font_mark, fill=(200, 210, 220))

    try:
        img = img.filter(ImageFilter.SMOOTH_MORE)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=80, threshold=2))
    except Exception:
        pass
    return img


def render_topic_illustration_stills(
    topic: str = "",
    *,
    n: int = 3,
    width: int = _W,
    height: int = _H,
    speaking: bool | None = None,
    duration_sec: float = 15.0,
    mouth_hold_sec: float = _MOUTH_HOLD_SEC,
    prefix: str | None = None,
    out_dir: Path | None = None,
) -> list[str]:
    """Write topic-aware illustration PNGs (mouth pairs when speak + face subject)."""
    dest_dir = Path(out_dir) if out_dir else IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = prefix or f"mira_illust_{uuid.uuid4().hex[:8]}"
    kind = detect_illustration_subject(topic)
    speak = wants_speaking(topic) if speaking is None else bool(speaking)
    can_mouth = speak and kind in _FACE_SUBJECTS
    paths: list[str] = []

    if can_mouth:
        pair: dict[str, str] = {}
        for open_mouth, tag in ((False, "closed"), (True, "open")):
            try:
                img = render_topic_illustration(
                    topic,
                    subject=kind,
                    mouth_open=open_mouth,
                    width=width,
                    height=height,
                    variant=0,
                )
                path = dest_dir / f"{stem}_{kind}_{tag}.png"
                img.save(path, format="PNG", optimize=True)
                if path.is_file() and path.stat().st_size > 800:
                    pair[tag] = str(path)
            except Exception:
                continue
        dur = max(3.0, float(duration_sec or 15.0))
        hold = max(0.35, min(0.55, float(mouth_hold_sec or _MOUTH_HOLD_SEC)))
        ticks = max(4, int(round(dur / hold)))
        if ticks % 2 == 1:
            ticks += 1
        closed, opened = pair.get("closed"), pair.get("open")
        for t in range(ticks):
            use_open = t % 2 == 1
            pick = opened if use_open and opened else closed
            if not pick:
                pick = opened or closed
            if pick:
                paths.append(pick)
        if paths:
            return paths

    need = max(3, int(n or 3))
    for i in range(need):
        try:
            img = render_topic_illustration(
                topic,
                subject=kind,
                mouth_open=False,
                width=width,
                height=height,
                variant=i,
            )
            path = dest_dir / f"{stem}_{kind}_{i}.png"
            img.save(path, format="PNG", optimize=True)
            if path.is_file() and path.stat().st_size > 800:
                paths.append(str(path))
        except Exception:
            continue
    return paths


def _draw_cute_face(
    draw: Any,
    cx: int,
    cy: int,
    scale: float,
    *,
    mouth_open: bool = False,
) -> None:
    """Simple eyes + smile / oval mouth — readable talking cue (AA via thick strokes)."""
    eye_r = max(6, int(14 * scale))
    eye_dx = int(38 * scale)
    eye_y = cy - int(18 * scale)
    # Whites
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        draw.ellipse(
            [ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r],
            fill=(255, 255, 255),
            outline=(40, 40, 50),
            width=max(1, int(2 * scale)),
        )
        # Pupils looking slightly toward camera center
        pr = max(3, int(eye_r * 0.55))
        px_off = int(-2 * scale * sign)
        draw.ellipse(
            [ex - pr + px_off, eye_y - pr + 1, ex + pr + px_off, eye_y + pr + 1],
            fill=(35, 35, 45),
        )
        # Highlight
        hr = max(1, pr // 3)
        draw.ellipse(
            [ex - pr // 2 - hr + px_off, eye_y - pr // 2 - hr, ex - pr // 2 + hr + px_off, eye_y - pr // 2 + hr],
            fill=(255, 255, 255),
        )
    # Cheeks
    cheek_r = max(5, int(12 * scale))
    for sign in (-1, 1):
        chx = cx + sign * int(52 * scale)
        chy = cy + int(8 * scale)
        draw.ellipse(
            [chx - cheek_r, chy - cheek_r // 2, chx + cheek_r, chy + cheek_r // 2],
            fill=(255, 170, 160),
        )
    # Mouth
    my = cy + int(28 * scale)
    if mouth_open:
        mw, mh = int(28 * scale), int(26 * scale)
        draw.ellipse(
            [cx - mw, my - mh // 3, cx + mw, my + mh],
            fill=(80, 30, 40),
            outline=(50, 20, 30),
            width=max(1, int(2 * scale)),
        )
        # Tongue hint
        tw, th = int(14 * scale), int(10 * scale)
        draw.ellipse(
            [cx - tw, my + int(6 * scale), cx + tw, my + int(6 * scale) + th],
            fill=(220, 90, 100),
        )
    else:
        # Closed smile arc via chord-ish thick ellipse slice
        mw, mh = int(32 * scale), int(18 * scale)
        draw.arc(
            [cx - mw, my - mh, cx + mw, my + mh // 2],
            start=20,
            end=160,
            fill=(50, 30, 40),
            width=max(3, int(5 * scale)),
        )


def _aa_ellipse(
    draw: Any,
    box: list[int],
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    width: int = 2,
) -> None:
    """Draw ellipse; Pillow ellipses are crisp enough at supersampled sizes."""
    draw.ellipse(box, fill=fill, outline=outline, width=max(1, width))


def render_fruit_character(
    kind: str,
    *,
    mouth_open: bool = False,
    width: int = _W,
    height: int = _H,
) -> Any:
    """Draw one clear cartoon fruit with a cute face on a bright kitchen bg.

    Soft SMOOTH_MORE pass + light unsharp for anti-aliased look without a full
    2× supersample (keeps free-path encode snappy).
    """
    from PIL import Image, ImageDraw, ImageFilter

    kind_l = (kind or "apple").strip().lower()
    if kind_l not in _FRUIT_KINDS:
        kind_l = "apple"

    W, H = int(width), int(height)
    img = Image.new("RGB", (W, H), (186, 214, 238))
    _draw_kitchen_bg(img, W, H)
    draw = ImageDraw.Draw(img)

    cx, cy = W // 2, int(H * 0.46)
    scale = min(W, H) / 720.0

    def _soft_ground_shadow(rx: int, ry: int, y_off: int = 0) -> None:
        """Soft oval contact shadow on the counter under the fruit."""
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFilter as _ImageFilter

        sh = _Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = _ImageDraw.Draw(sh)
        shy = int(H * 0.76) + y_off
        sd.ellipse(
            [cx - rx, shy - ry, cx + rx, shy + ry],
            fill=(60, 40, 25, 90),
        )
        sh = sh.filter(_ImageFilter.GaussianBlur(radius=max(6, W // 120)))
        nonlocal img, draw
        img = _Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB")
        draw = ImageDraw.Draw(img)

    if kind_l == "apple":
        body = (220, 45, 55)
        shadow = (160, 25, 35)
        hi = (255, 120, 130)
        r = int(165 * scale)
        _soft_ground_shadow(int(130 * scale), int(28 * scale))
        # Soft body depth shadow (offset, muted — not a second fruit)
        _aa_ellipse(
            draw,
            [cx - r + int(10 * scale), cy - r + int(18 * scale), cx + r + int(10 * scale), cy + r + int(18 * scale)],
            fill=(160, 120, 90),
        )
        _aa_ellipse(draw, [cx - r, cy - r, cx + r, cy + r], fill=body, outline=shadow, width=max(3, int(3 * scale)))
        # Specular highlight (left-upper)
        hr = int(48 * scale)
        hx, hy = cx - int(55 * scale), cy - int(55 * scale)
        _aa_ellipse(draw, [hx - hr, hy - hr // 2, hx + hr // 2, hy + hr], fill=hi)
        # Dimple / crease
        draw.arc(
            [cx - int(40 * scale), cy - r - int(10 * scale), cx + int(40 * scale), cy - r + int(50 * scale)],
            start=200,
            end=340,
            fill=shadow,
            width=max(2, int(3 * scale)),
        )
        # Leaf
        lx, ly = cx + int(30 * scale), cy - r - int(10 * scale)
        _aa_ellipse(
            draw,
            [lx, ly - int(28 * scale), lx + int(55 * scale), ly + int(18 * scale)],
            fill=(70, 160, 70),
            outline=(40, 110, 50),
            width=max(2, int(2 * scale)),
        )
        # Stem
        draw.rectangle(
            [cx - int(6 * scale), cy - r - int(35 * scale), cx + int(6 * scale), cy - r + 4],
            fill=(90, 55, 30),
        )
        face_cy = cy + int(10 * scale)
        face_cx = cx
    elif kind_l == "banana":
        body = (250, 210, 50)
        shadow = (200, 150, 30)
        hi = (255, 245, 160)
        _soft_ground_shadow(int(120 * scale), int(26 * scale), y_off=int(8 * scale))
        # Curved banana via overlapping ellipses (clear crescent silhouette)
        pts = [
            (cx - int(40 * scale), cy + int(80 * scale), int(70 * scale), int(90 * scale)),
            (cx - int(10 * scale), cy + int(10 * scale), int(75 * scale), int(95 * scale)),
            (cx + int(30 * scale), cy - int(60 * scale), int(70 * scale), int(85 * scale)),
            (cx + int(55 * scale), cy - int(120 * scale), int(50 * scale), int(55 * scale)),
        ]
        for px, py, rw, rh in pts:
            _aa_ellipse(
                draw,
                [px - rw, py - rh, px + rw, py + rh],
                fill=body,
                outline=shadow,
                width=max(2, int(2 * scale)),
            )
        # Inner highlight ridge
        _aa_ellipse(
            draw,
            [
                cx - int(25 * scale),
                cy - int(20 * scale),
                cx + int(35 * scale),
                cy + int(70 * scale),
            ],
            fill=hi,
        )
        # Tip
        tip_x, tip_y = cx + int(70 * scale), cy - int(150 * scale)
        _aa_ellipse(
            draw,
            [tip_x - int(22 * scale), tip_y - int(18 * scale), tip_x + int(18 * scale), tip_y + int(22 * scale)],
            fill=(120, 80, 40),
        )
        # Stem nub at bottom
        _aa_ellipse(
            draw,
            [
                cx - int(70 * scale),
                cy + int(140 * scale),
                cx - int(30 * scale),
                cy + int(175 * scale),
            ],
            fill=(100, 70, 35),
        )
        face_cy = cy + int(5 * scale)
        face_cx = cx + int(5 * scale)
    else:  # orange
        body = (255, 140, 40)
        shadow = (200, 90, 20)
        hi = (255, 200, 120)
        r = int(160 * scale)
        _soft_ground_shadow(int(125 * scale), int(28 * scale))
        _aa_ellipse(
            draw,
            [cx - r + int(10 * scale), cy - r + int(16 * scale), cx + r + int(10 * scale), cy + r + int(16 * scale)],
            fill=(160, 120, 90),
        )
        _aa_ellipse(draw, [cx - r, cy - r, cx + r, cy + r], fill=body, outline=shadow, width=max(3, int(3 * scale)))
        # Specular
        hr = int(44 * scale)
        hx, hy = cx - int(50 * scale), cy - int(50 * scale)
        _aa_ellipse(draw, [hx - hr, hy - hr // 2, hx + hr // 2, hy + hr], fill=hi)
        # Subtle texture dots (peel pores)
        for dx, dy in ((-40, -30), (50, -20), (-20, 40), (35, 50), (0, -55), (60, 30), (-55, 15)):
            ox = cx + int(dx * scale)
            oy = cy + int(dy * scale)
            dr = max(2, int(4 * scale))
            _aa_ellipse(draw, [ox - dr, oy - dr, ox + dr, oy + dr], fill=(240, 120, 30))
        # Leaf
        lx, ly = cx + int(20 * scale), cy - r - int(5 * scale)
        _aa_ellipse(
            draw,
            [lx, ly - int(22 * scale), lx + int(48 * scale), ly + int(14 * scale)],
            fill=(70, 160, 70),
            outline=(40, 110, 50),
            width=max(2, int(2 * scale)),
        )
        draw.rectangle(
            [cx - int(5 * scale), cy - r - int(28 * scale), cx + int(5 * scale), cy - r + 2],
            fill=(90, 55, 30),
        )
        face_cy = cy + int(8 * scale)
        face_cx = cx

    _draw_cute_face(draw, face_cx, face_cy, scale * 1.15, mouth_open=mouth_open)

    # Tiny Mira mark (no topic text)
    font_mark = _load_font(max(14, H // 40), bold=False)
    draw.text((int(W * 0.04), H - int(H * 0.06)), "Mira", font=font_mark, fill=(160, 150, 140))

    # Light smooth + unsharp for cleaner edges (not goo blobs)
    try:
        img = img.filter(ImageFilter.SMOOTH_MORE)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=90, threshold=2))
    except Exception:
        pass
    return img


def render_fruit_character_stills(
    topic: str = "",
    *,
    n: int = 3,
    width: int = _W,
    height: int = _H,
    speaking: bool | None = None,
    duration_sec: float = 15.0,
    mouth_hold_sec: float = _MOUTH_HOLD_SEC,
    prefix: str | None = None,
    out_dir: Path | None = None,
) -> list[str]:
    """Write clear cartoon fruit PNGs — never blobs, never abstract gradients.

    Non-speaking: ≥3 distinct fruit characters (apple, banana, orange).
    Speaking: mouth-closed + mouth-open pairs, sequenced ~0.45s alternation per
    character segment so the slideshow looks like talking.
    """
    return render_talking_fruit_stills(
        topic,
        n=n,
        width=width,
        height=height,
        speaking=speaking,
        duration_sec=duration_sec,
        mouth_hold_sec=mouth_hold_sec,
        prefix=prefix,
        out_dir=out_dir,
    )


def render_talking_fruit_stills(
    topic: str = "",
    *,
    n: int = 3,
    width: int = _W,
    height: int = _H,
    speaking: bool | None = None,
    duration_sec: float = 15.0,
    mouth_hold_sec: float = _MOUTH_HOLD_SEC,
    prefix: str | None = None,
    out_dir: Path | None = None,
) -> list[str]:
    """Canonical local talking-fruit still generator (ONLY path for fruit topics).

    Exactly 3 characters — Apple, Banana, Orange — each FULL FRAME single subject
    (never a grid / collage). Mouth closed + open variants assemble at ~0.45s.
    """
    dest_dir = Path(out_dir) if out_dir else IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = prefix or f"mira_fruit_{uuid.uuid4().hex[:8]}"
    speak = wants_speaking(topic) if speaking is None else bool(speaking)
    # Fruit topics always prefer speaking pairs when topic implies talk/describe
    if speaking is None and is_fruit_topic(topic) and not speak:
        # Still emit 3 distinct fruits; caller may force speaking=True
        pass
    paths: list[str] = []

    # Always materialize base closed/open frames for each fruit
    pair_paths: dict[str, dict[str, str]] = {}
    for kind in _FRUIT_KINDS:
        pair_paths[kind] = {}
        for open_mouth, tag in ((False, "closed"), (True, "open")):
            try:
                img = render_fruit_character(
                    kind, mouth_open=open_mouth, width=width, height=height
                )
                path = dest_dir / f"{stem}_{kind}_{tag}.png"
                img.save(path, format="PNG", optimize=True)
                if path.is_file() and path.stat().st_size > 800:
                    pair_paths[kind][tag] = str(path)
            except Exception:
                continue

    if speak:
        # Sequence: for each fruit segment, alternate closed/open every mouth_hold_sec
        dur = max(3.0, float(duration_sec or 15.0))
        hold = max(0.35, min(0.55, float(mouth_hold_sec or _MOUTH_HOLD_SEC)))
        seg = dur / max(1, len(_FRUIT_KINDS))
        ticks_per_seg = max(2, int(round(seg / hold)))
        # Keep even so we end on a closed or open pair cleanly
        if ticks_per_seg % 2 == 1:
            ticks_per_seg += 1
        for kind in _FRUIT_KINDS:
            closed = pair_paths.get(kind, {}).get("closed")
            opened = pair_paths.get(kind, {}).get("open")
            if not closed and not opened:
                continue
            for t in range(ticks_per_seg):
                use_open = t % 2 == 1
                pick = opened if use_open and opened else closed
                if not pick:
                    pick = opened or closed
                if pick:
                    paths.append(pick)
        if paths:
            return paths

    # Non-speaking (or speak failed): 3 distinct fruit frames (closed mouth)
    need = max(3, int(n or 3))
    for i in range(need):
        kind = _FRUIT_KINDS[i % len(_FRUIT_KINDS)]
        p = pair_paths.get(kind, {}).get("closed") or pair_paths.get(kind, {}).get("open")
        if p:
            paths.append(p)
    return paths[:need] if paths else paths


def looks_like_goo_or_blob(path: str | Path) -> bool:
    """Reject translucent orange/yellow goo / low-detail abstract AI junk."""
    try:
        from PIL import Image, ImageFilter, ImageStat
    except Exception:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    try:
        img = Image.open(p).convert("RGB").resize((128, 128), Image.Resampling.BILINEAR)
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_mean = float(ImageStat.Stat(edges).mean[0])
        lum_var = float(ImageStat.Stat(gray).var[0])
        # Very soft / blurry with little structure → goo or abstract pad
        if edge_mean < 10.0 and lum_var < 900.0:
            return True
        # Dominant warm orange-yellow with almost no edges (classic Pollinations goo)
        r, g, b = ImageStat.Stat(img).mean
        warm = r > 140 and g > 90 and b < 120 and (r - b) > 40
        if warm and edge_mean < 14.0 and lum_var < 1400.0:
            return True
        if edge_mean < 6.5:
            return True
    except Exception:
        return False
    return False


def render_hero_opener(
    *,
    title: str = "VERIDIQ",
    subtitle: str = "Truth. Verified. Empowered.",
    width: int = _W,
    height: int = _H,
) -> Any:
    """Premium centered poster for brand shot 0 — wordmark + accent line + short tagline.

    High contrast, bright enough midnight + electric blue. No body text dump,
    no scene labels, no creature/spotlight blobs.
    """
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", (width, height), _BG_TOP)
    _draw_gradient(img, _BG_TOP, _BG_BOT)
    draw = ImageDraw.Draw(img)
    _draw_subtle_grid(draw, width, height)

    # Soft centered glow (wide, even — not a creature spotlight)
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx, cy = width // 2, int(height * 0.42)
    rx, ry = int(width * 0.42), int(height * 0.28)
    gdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(20, 70, 140))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(60, width // 14)))
    img = Image.blend(img, glow, 0.22)
    draw = ImageDraw.Draw(img)

    # Thin electric-blue frame accents (top + bottom rules)
    draw.rectangle([0, 0, width, 3], fill=_ACCENT)
    draw.rectangle([0, height - 3, width, height], fill=_ACCENT)
    bar_w = max(4, width // 160)
    draw.rectangle([0, 0, bar_w, height], fill=_ACCENT)
    draw.rectangle([width - bar_w, 0, width, height], fill=_ACCENT)

    brand = (title or "VERIDIQ").strip()
    if re.search(r"\bscene\b", brand, re.I) or len(brand) > 48:
        brand = "VERIDIQ"
    tag = (subtitle or "Truth. Verified. Empowered.").strip()
    if re.search(r"\bscene\b", tag, re.I) or len(tag) > 64:
        tag = "Truth. Verified. Empowered."

    # Large centered wordmark
    font_brand = _load_font(max(72, height // 7), bold=True)
    font_tag = _load_font(max(26, height // 20), bold=False)

    max_tw = int(width * 0.86)
    brand = _fit_text(draw, brand.upper(), font_brand, max_tw)
    try:
        bw = draw.textlength(brand, font=font_brand)
    except Exception:
        bw = len(brand) * (height // 10)
    bx = int((width - bw) / 2)
    by = int(height * 0.34)
    # Soft shadow for readability
    draw.text((bx + 2, by + 2), brand, font=font_brand, fill=(4, 8, 18))
    draw.text((bx, by), brand, font=font_brand, fill=_TITLE)

    # Thin electric blue accent line under wordmark
    try:
        brand_h = font_brand.size if hasattr(font_brand, "size") else height // 7
    except Exception:
        brand_h = height // 7
    line_y = by + int(brand_h * 1.15)
    line_w = max(int(width * 0.12), int(bw * 0.35))
    draw.rectangle(
        [width // 2 - line_w // 2, line_y, width // 2 + line_w // 2, line_y + 3],
        fill=_ACCENT,
    )

    # Short tagline — no body dump
    tag = _fit_text(draw, tag, font_tag, max_tw)
    if tag:
        try:
            tw = draw.textlength(tag, font=font_tag)
        except Exception:
            tw = len(tag) * 10
        tx = int((width - tw) / 2)
        ty = line_y + int(height * 0.06)
        draw.text((tx, ty), tag, font=font_tag, fill=_SUB)

    return img


def render_branded_frame(
    *,
    title: str,
    subtitle: str = "",
    eyebrow: str = "VERIDIQ",
    footer: str = "",
    width: int = _W,
    height: int = _H,
    variant: int = 0,
    layout: str = "card",
    subject: str = "",
    topic: str = "",
) -> Any:
    """Create one intentional still (PIL Image RGB).

    layout='hero' → premium centered poster (brand shot 0).
    layout='card' → supporting product-card aesthetic.
    layout='abstract' → cinematic gradient, no topic text.
    layout='fruit' → clear cartoon fruit character (never abstract goo).
    layout='illustration' → topic-aware local subject on scenic bg.
    """
    layout_l = (layout or "").lower()
    if layout_l == "fruit":
        kind = "apple"
        # Allow callers to pass fruit via title field as a soft hint
        t = (title or "").strip().lower()
        if t in _FRUIT_KINDS:
            kind = t
        return render_fruit_character(kind, mouth_open=False, width=width, height=height)
    if layout_l == "illustration":
        return render_topic_illustration(
            topic or title or "",
            subject=(subject or None),
            mouth_open=False,
            width=width,
            height=height,
            variant=variant,
        )
    if layout_l == "abstract":
        # Prefer topic illustration over bare abstract when we can detect a subject
        subj = (subject or detect_illustration_subject(topic or title or "")).strip()
        if subj and subj != "scenic":
            return render_topic_illustration(
                topic or title or "",
                subject=subj,
                width=width,
                height=height,
                variant=variant,
            )
        return render_abstract_frame(width=width, height=height, variant=variant)
    if layout_l == "hero":
        return render_hero_opener(
            title=title or "VERIDIQ",
            subtitle=subtitle or "Truth. Verified. Empowered.",
            width=width,
            height=height,
        )

    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", (width, height), _BG_TOP)
    _draw_gradient(img, _BG_TOP, _BG_BOT)
    draw = ImageDraw.Draw(img)

    # Soft accent glow (intentional atmosphere, not muddy creature)
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx = int(width * (0.72 + 0.04 * (variant % 3)))
    cy = int(height * (0.35 + 0.08 * ((variant + 1) % 3)))
    r = int(min(width, height) * 0.38)
    gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_ACCENT_DIM)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(40, width // 18)))
    img = Image.blend(img, glow, 0.22)
    draw = ImageDraw.Draw(img)

    # Product card panel (dark midnight + electric blue edge)
    card_m = int(width * 0.06)
    card_top = int(height * 0.14)
    card_bot = int(height * 0.78)
    draw.rounded_rectangle(
        [card_m, card_top, width - card_m, card_bot],
        radius=max(12, width // 64),
        fill=_CARD,
        outline=_CARD_EDGE,
        width=max(2, width // 400),
    )

    # Left accent bar
    bar_w = max(6, width // 120)
    draw.rectangle([0, 0, bar_w, height], fill=_ACCENT)

    # Thin top rule
    draw.rectangle([0, 0, width, 3], fill=_ACCENT)

    pad = int(width * 0.10)
    max_tw = width - pad * 2

    font_eye = _load_font(max(18, height // 28), bold=True)
    font_title = _load_font(max(42, height // 10), bold=True)
    font_sub = _load_font(max(22, height // 22), bold=False)
    font_foot = _load_font(max(16, height // 32), bold=False)

    y = int(height * 0.22)
    eye = _fit_text(draw, (eyebrow or "VERIDIQ").upper(), font_eye, max_tw)
    if "SCENE" in eye.upper():
        eye = "VERIDIQ"
    if eye:
        draw.text((pad, y), eye, font=font_eye, fill=_ACCENT)
    y += int(height * 0.08)

    # Title — brand short copy only (never dump creative prompts)
    title_txt = (title or "VERIDIQ").strip()
    if not _is_veridiq_topic(title_txt) and (
        len(title_txt) > 40
        or _looks_like_command(title_txt)
        or len(title_txt.split()) >= 4
    ):
        title_txt = "VERIDIQ"
    elif re.search(r"\bscene\b", title_txt, re.I):
        title_txt = "VERIDIQ"
    words = title_txt.split()
    line1, line2 = title_txt, ""
    if len(words) > 3:
        mid = max(1, len(words) // 2)
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
    line1 = _fit_text(draw, line1, font_title, max_tw)
    draw.text((pad, y), line1, font=font_title, fill=_TITLE)
    y += int(height * 0.12)
    if line2:
        line2 = _fit_text(draw, line2, font_title, max_tw)
        draw.text((pad, y), line2, font=font_title, fill=_TITLE)
        y += int(height * 0.11)

    y += int(height * 0.02)
    draw.rectangle([pad, y, pad + int(width * 0.18), y + 4], fill=_ACCENT)
    y += int(height * 0.06)

    sub = _fit_text(draw, subtitle, font_sub, max_tw)
    if sub and "scene" not in sub.lower():
        draw.text((pad, y), sub, font=font_sub, fill=_SUB)

    foot = _fit_text(draw, footer or "", font_foot, max_tw)
    if foot and "scene" not in foot.lower():
        draw.text((pad, height - int(height * 0.10)), foot, font=font_foot, fill=_MUTED)

    mark = "VQ"
    draw.text((width - pad - 36, height - int(height * 0.10)), mark, font=font_foot, fill=_ACCENT_DIM)

    return img


def generate_local_hero_opener(
    topic: str,
    *,
    width: int = _W,
    height: int = _H,
    prefix: str | None = None,
    out_dir: Path | None = None,
) -> Optional[str]:
    """Write shot-0 PNG. Brand → VERIDIQ hero; fruit → fruit; else topic illustration."""
    dest_dir = Path(out_dir) if out_dir else IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = prefix or f"mira_local_{uuid.uuid4().hex[:8]}"
    try:
        if _is_veridiq_topic(topic):
            fr = frame_copy_for_topic(topic, n=1)[0]
            img = render_hero_opener(
                title=fr.get("title") or "VERIDIQ",
                subtitle=fr.get("subtitle") or "Truth. Verified. Empowered.",
                width=width,
                height=height,
            )
            path = dest_dir / f"{stem}_hero_0.png"
        elif is_fruit_topic(topic):
            paths = render_talking_fruit_stills(
                topic,
                n=1,
                width=width,
                height=height,
                speaking=False,
                prefix=stem,
                out_dir=dest_dir,
            )
            return paths[0] if paths else None
        else:
            paths = render_topic_illustration_stills(
                topic,
                n=1,
                width=width,
                height=height,
                speaking=False,
                prefix=stem,
                out_dir=dest_dir,
            )
            return paths[0] if paths else None
        img.save(path, format="PNG", optimize=True)
        if path.is_file() and path.stat().st_size > 800:
            return str(path)
    except Exception:
        return None
    return None


def generate_local_stills(
    topic: str,
    *,
    n: int = 3,
    width: int = _W,
    height: int = _H,
    prefix: str | None = None,
    out_dir: Path | None = None,
    speaking: bool | None = None,
    duration_sec: float = 15.0,
) -> list[str]:
    """Write n local PNG stills; always returns existing file paths (or empty on hard fail).

    Brand → hero + titled cards.
    Fruit / speaking-fruit → clear cartoon fruit characters (talking pairs when speak).
    Other creative → topic-aware illustrations (no prompt text).
    """
    dest_dir = Path(out_dir) if out_dir else IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = prefix or f"mira_local_{uuid.uuid4().hex[:8]}"

    # Fruit topics: never abstract gradients / never AI
    if is_fruit_topic(topic):
        fruit_paths = render_talking_fruit_stills(
            topic,
            n=max(3, int(n or 3)),
            width=width,
            height=height,
            speaking=speaking,
            duration_sec=duration_sec,
            prefix=stem,
            out_dir=dest_dir,
        )
        if fruit_paths:
            return fruit_paths

    # Non-brand creative / character: topic-aware illustrations (mouth pairs when speak)
    if not _is_veridiq_topic(topic):
        illust = render_topic_illustration_stills(
            topic,
            n=max(3, int(n or 3)),
            width=width,
            height=height,
            speaking=speaking,
            duration_sec=duration_sec,
            prefix=stem,
            out_dir=dest_dir,
        )
        if illust:
            return illust

    frames = frame_copy_for_topic(topic, n=n)
    paths: list[str] = []
    for i, fr in enumerate(frames):
        try:
            layout = fr.get("layout") or ("hero" if i == 0 else "card")
            # Fruit frame: use fruit kind from descriptor
            title = fr.get("title") or ""
            if layout == "fruit":
                title = fr.get("fruit") or _FRUIT_KINDS[i % len(_FRUIT_KINDS)]
            img = render_branded_frame(
                title=title,
                subtitle=fr.get("subtitle") or "",
                eyebrow=fr.get("eyebrow") or "VERIDIQ",
                footer=fr.get("footer") or "",
                width=width,
                height=height,
                variant=i,
                layout=layout,
                subject=fr.get("subject") or "",
                topic=topic,
            )
            if layout == "hero":
                suffix = "hero_0"
            elif layout == "abstract":
                suffix = f"abstract_{i}"
            elif layout == "illustration":
                suffix = f"illust_{i}"
            elif layout == "fruit":
                suffix = f"fruit_{i}"
            else:
                suffix = f"local_{i}"
            path = dest_dir / f"{stem}_{suffix}.png"
            img.save(path, format="PNG", optimize=True)
            if path.is_file() and path.stat().st_size > 800:
                paths.append(str(path))
        except Exception:
            continue
    return paths


def ensure_still_set(
    ai_paths: list[str] | None,
    topic: str,
    *,
    n: int = 3,
    width: int = _W,
    height: int = _H,
    prefix: str | None = None,
    force_local: bool = False,
    hero_opener: bool | None = None,
    duration_sec: float = 15.0,
    speaking: bool | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Guarantee ≥n stills.

    Brand (default hero_opener=True):
      stills = [local_hero] + ai[:n-1]  (or all local when force_local)

    Fruit / speaking character topics:
      NEVER pad with abstract gradients — local drawn fruit characters
      (talking mouth open/close pairs when speaking). Prefer local as primary
      for fruit+speak. Source key: local_talking_fruits. ZERO AI / Pollinations.

    Other creative (default hero_opener=False):
      stills = ai[:n] padded with topic-aware local illustrations — never topic-title cards.
    """
    brand = _is_veridiq_topic(topic)
    fruit = is_fruit_topic(topic)
    speak = wants_speaking(topic) if speaking is None else bool(speaking)
    character = is_character_topic(topic)
    illust_kind = detect_illustration_subject(topic) if not brand and not fruit else ""
    if hero_opener is None:
        hero_opener = brand

    # Fruit topics: discard ALL AI paths — Pollinations grids/goo must never win
    if fruit:
        ai = []
    else:
        ai = [p for p in (ai_paths or []) if p and Path(p).is_file()]
    # Drop AI goo/blob/collage frames for speaking character topics
    if (not fruit) and (character and speak):
        cleaned: list[str] = []
        for p in ai:
            try:
                if looks_like_goo_or_blob(p):
                    continue
                from veridiq.postings.creative import looks_like_collage_or_grid

                if looks_like_collage_or_grid(p):
                    continue
            except Exception:
                pass
            cleaned.append(p)
        ai = cleaned

    need = max(1, int(n))
    meta: dict[str, Any] = {
        "ai_count": 0 if fruit else len(ai),
        "local_count": 0,
        "source": "ai",
        "forced": bool(force_local),
        "hero_opener": bool(hero_opener),
        "brand": brand,
        "creative_abstract": False,
        "is_fruit": fruit,
        "speaking": speak,
        "character_topic": character,
        "illustration_subject": illust_kind or None,
        "pollinations_calls": 0 if fruit else None,
        "local_talking_fruits": bool(fruit),
    }

    # --- Fruit topics: ONLY render_talking_fruit_stills — never AI, never abstract ---
    if fruit:
        local = render_talking_fruit_stills(
            topic,
            n=max(3, need),
            width=width,
            height=height,
            speaking=True if speak else speak,
            duration_sec=duration_sec,
            prefix=prefix,
            out_dir=None,
        )
        # Speaking fruit topics always get mouth pairs; non-speak still gets 3 fruits
        if not local:
            local = render_talking_fruit_stills(
                topic or "talking fruits",
                n=max(3, need),
                width=width,
                height=height,
                speaking=True,
                duration_sec=duration_sec,
                prefix=prefix or "fruit_retry",
            )
        meta["local_count"] = len(local)
        meta["source"] = "local_talking_fruits"
        meta["opener"] = "fruit_character"
        meta["mouth_variants"] = bool(speak) or any(
            "open" in Path(p).name.lower() for p in (local or [])
        )
        meta["talking_note"] = (
            "Talking fruit animation (mouth open/close stills) — not neural lip-sync"
        )
        meta["creative_abstract"] = False
        meta["pollinations_calls"] = 0
        meta["fruit_local_primary"] = True
        meta["local_talking_fruits"] = True
        meta["ai_count"] = 0
        return local if local else [], meta

    # --- Character (non-fruit) speaking: never abstract gradient pad ---
    if character and speak and not brand:
        if not force_local and len(ai) >= need:
            meta["source"] = "ai"
            meta["opener"] = "ai"
            meta["creative_abstract"] = False
            return ai[:need], meta
        if ai:
            # Repeat AI frames rather than abstract goo pads
            mixed = list(ai)
            while len(mixed) < need:
                mixed.append(ai[len(mixed) % len(ai)])
            meta["source"] = "ai_cycled"
            meta["opener"] = "ai"
            meta["creative_abstract"] = False
            meta["local_count"] = 0
            return mixed[:need], meta
        # No AI — topic-aware local character (mouth pairs when drawable)
        local = render_topic_illustration_stills(
            topic,
            n=max(3, need),
            width=width,
            height=height,
            speaking=True,
            duration_sec=duration_sec,
            prefix=prefix,
        )
        meta["local_count"] = len(local)
        meta["source"] = "local_illustration"
        meta["opener"] = "illustration"
        meta["creative_abstract"] = False
        meta["mouth_variants"] = any(
            ("_open" in Path(p).name.lower() or "_closed" in Path(p).name.lower())
            for p in (local or [])
        )
        meta["illustration_subject"] = illust_kind or detect_illustration_subject(topic)
        meta["local_talking_fruits"] = False
        meta["pollinations_calls"] = 0
        return local if local else [], meta

    # --- Creative path: AI first, topic-illustration pad, no topic-title hero ---
    if not brand:
        if not force_local and len(ai) >= need:
            meta["source"] = "ai"
            meta["opener"] = "ai"
            meta["creative_abstract"] = False
            return ai[:need], meta

        local = generate_local_stills(
            topic,
            n=need,
            width=width,
            height=height,
            prefix=prefix,
            speaking=speak,
            duration_sec=duration_sec,
        )
        meta["local_count"] = len(local)
        meta["creative_abstract"] = False
        meta["illustration_subject"] = illust_kind or detect_illustration_subject(topic)
        if force_local or len(ai) == 0:
            mixed = local[:need]
            meta["source"] = "local_illustration"
            meta["opener"] = "illustration"
        else:
            mixed = (ai + local)[:need]
            meta["source"] = "mixed" if local else "ai"
            meta["opener"] = "ai"
            meta["ai_used"] = min(len(ai), need)
            meta["local_count"] = max(0, len(mixed) - min(len(ai), need))
        if len(mixed) < 1:
            local2 = render_topic_illustration_stills(
                topic or "cinematic scenic",
                n=need,
                width=width,
                height=height,
                prefix=prefix,
            )
            mixed = local2[:need]
            meta["local_count"] = len(local2)
            meta["source"] = "local_illustration"
            meta["retried"] = True
            meta["opener"] = "illustration"
        return mixed, meta

    # --- Brand path: hero opener owns index 0 ---
    if hero_opener:
        hero = generate_local_hero_opener(
            topic, width=width, height=height, prefix=prefix
        )
        if not hero:
            local_all = generate_local_stills(
                topic, n=need, width=width, height=height, prefix=prefix
            )
            if local_all:
                meta["local_count"] = len(local_all)
                meta["source"] = "local"
                meta["hero_opener"] = True
                return local_all[:need], meta
            return [], meta

        support_need = need - 1
        if force_local or support_need <= 0:
            rest: list[str] = []
            if support_need > 0:
                local_all = generate_local_stills(
                    topic, n=need, width=width, height=height, prefix=prefix
                )
                rest = [p for p in local_all[1:] if p != hero][:support_need]
            mixed = ([hero] + rest)[:need]
            while len(mixed) < need:
                pad = generate_local_stills(
                    topic, n=need, width=width, height=height, prefix=f"{prefix or 'mira'}_pad"
                )
                for p in pad[1:] if pad else pad:
                    if p not in mixed:
                        mixed.append(p)
                    if len(mixed) >= need:
                        break
                break
            meta["local_count"] = len(mixed)
            meta["ai_used_after_hero"] = 0
            meta["source"] = "local"
            meta["opener"] = "local_hero"
            return mixed[:need], meta

        ai_support = ai[:support_need]
        rest = list(ai_support)
        if len(rest) < support_need:
            local_all = generate_local_stills(
                topic, n=need, width=width, height=height, prefix=prefix
            )
            for p in local_all[1:]:
                if p == hero:
                    continue
                rest.append(p)
                if len(rest) >= support_need:
                    break
        mixed = ([hero] + rest)[:need]
        meta["local_count"] = 1 + max(0, len(mixed) - 1 - len(ai_support))
        meta["ai_used_after_hero"] = len(ai_support)
        meta["opener"] = "local_hero"
        if len(ai_support) == 0:
            meta["source"] = "local"
            meta["local_count"] = len(mixed)
        elif len(ai_support) >= support_need:
            meta["source"] = "mixed"
            meta["local_count"] = 1
        else:
            meta["source"] = "mixed"
        return mixed, meta

    # --- Legacy brand path (hero_opener=False) ---
    if not force_local and len(ai) >= need:
        return ai[:need], meta

    local_need = need if force_local and len(ai) == 0 else max(0, need - len(ai))
    if force_local and len(ai) < need:
        local_need = need - len(ai)
    if len(ai) == 0:
        local_need = need
        force_local = True

    local = generate_local_stills(
        topic,
        n=max(local_need, need if force_local else local_need),
        width=width,
        height=height,
        prefix=prefix,
    )
    meta["local_count"] = len(local)

    if force_local and len(ai) == 0:
        mixed = local[:need]
        meta["source"] = "local"
    elif len(ai) == 0:
        mixed = local[:need]
        meta["source"] = "local"
    else:
        mixed = (ai + local)[:need]
        meta["source"] = "mixed" if local else "ai"

    if len(mixed) < 1:
        local2 = generate_local_stills(
            topic or "VERIDIQ", n=need, width=width, height=height, prefix=prefix
        )
        mixed = local2[:need]
        meta["local_count"] = len(local2)
        meta["source"] = "local"
        meta["retried"] = True

    return mixed, meta


def veridiq_narration_script(topic: str = "") -> str:
    """Polished free VO — delegates to build_narration_script (no scene indices)."""
    try:
        from veridiq.postings.creative import build_narration_script

        return build_narration_script(topic, duration_hint_sec=15)
    except Exception:
        if _is_veridiq_topic(topic) or not (topic or "").strip():
            return (
                "Welcome to VERIDIQ — where truth meets intelligence. "
                "Our AI agents work together in a live workspace to verify claims, "
                "investigate signals, and deliver trusted reports. "
                "Truth. Verified. Empowered."
            )
        title = _clean_topic_title(topic) or "this story"
        return (
            f"Here's a clear look at {title}. "
            f"What matters most comes through in a few sharp beats. "
            f"Stay with it — this is {title}, explained."
        )
