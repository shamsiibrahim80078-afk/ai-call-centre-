"""Free image generation via Pollinations (image.pollinations.ai).

No API key required for basic prompts. Downloads a real JPEG and stores it
under marketing_out/images/ — never invents a fake image URL.

Prompt strategy: lock the user's subject FIRST (gender/identity preserved),
add quality tags only, never overwrite with brand logos or conflicting people.

Rate limit: Pollinations free tier allows ~1 in-flight request per IP.
All downloads share a process-wide semaphore so image + video stills
do not 429 each other.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from veridiq.integrations.base import status_shape

PLATFORM = "pollinations_image"
DISPLAY = "Pollinations Image (free)"
CATEGORY = "creative"
ENV_VARS: list[str] = []
CAPABILITIES = ["generate_image", "generate_images_parallel"]
DOCS = "https://image.pollinations.ai/"

_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = _ROOT / "marketing_out" / "images"
BASE = "https://image.pollinations.ai/prompt"
# Alternate free hosts (same Pollinations network / compatible prompt URL)
ALT_BASES = (
    "https://image.pollinations.ai/prompt",
    "https://gen.pollinations.ai/image",
)

# Prefer Flux for quality; fall back handled by Pollinations if model missing
DEFAULT_MODEL = "flux"
FALLBACK_MODELS = ("flux", "turbo")

# Global: only 1 Pollinations image HTTP request in flight (image + video stills)
_POLL_SEM = threading.Semaphore(1)
_RETRY_BACKOFF_SEC = (3.0, 6.0, 10.0)  # waits before tries 2–4


def pollinations_slot(timeout: float | None = None):
    """Context manager / acquire helper for shared Pollinations IP queue."""
    return _PollSlot(timeout)


class _PollSlot:
    def __init__(self, timeout: float | None = None) -> None:
        self._timeout = timeout
        self._held = False

    def __enter__(self) -> "_PollSlot":
        if self._timeout is None:
            self._held = _POLL_SEM.acquire(blocking=True)
        else:
            self._held = _POLL_SEM.acquire(blocking=True, timeout=max(0.1, float(self._timeout)))
            if not self._held:
                raise TimeoutError("Pollinations queue busy — retry in a few seconds.")
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._held:
            _POLL_SEM.release()
            self._held = False

# Subject / identity tokens we must never strip or overwrite
_MALE = frozenset(
    {
        "boy",
        "boys",
        "man",
        "men",
        "male",
        "guy",
        "guys",
        "gentleman",
        "father",
        "dad",
        "brother",
        "son",
        "king",
        "prince",
        "he",
        "him",
        "his",
        "himself",
    }
)
_FEMALE = frozenset(
    {
        "girl",
        "girls",
        "woman",
        "women",
        "female",
        "lady",
        "ladies",
        "mother",
        "mom",
        "sister",
        "daughter",
        "queen",
        "princess",
        "she",
        "her",
        "hers",
        "herself",
    }
)
_SUBJECT_NOUNS = frozenset(
    {
        "dog",
        "cat",
        "car",
        "truck",
        "bike",
        "motorcycle",
        "horse",
        "bird",
        "robot",
        "athlete",
        "bodybuilder",
        "fitness",
        "gym",
        "child",
        "kid",
        "baby",
        "teen",
        "teenager",
        "couple",
        "family",
        "chef",
        "doctor",
        "nurse",
        "soldier",
        "pilot",
        "teacher",
        "student",
        "singer",
        "dancer",
        "gamer",
        "hacker",
        "astronaut",
        "dragon",
        "tiger",
        "lion",
        "wolf",
        "fox",
        "bear",
        "elephant",
        "airplane",
        "ship",
        "boat",
        "train",
        "motorcycle",
        "scooter",
        "building",
        "city",
        "beach",
        "mountain",
        "forest",
        "office",
        "desk",
        "agent",
        "agents",
        # Food / fruit / object characters (must never become humans)
        "fruit",
        "fruits",
        "apple",
        "apples",
        "banana",
        "bananas",
        "orange",
        "oranges",
        "grape",
        "grapes",
        "strawberry",
        "strawberries",
        "watermelon",
        "pineapple",
        "mango",
        "peach",
        "pear",
        "lemon",
        "cherry",
        "berries",
        "vegetable",
        "vegetables",
        "tomato",
        "carrot",
        "food",
        "foods",
        "toy",
        "toys",
        "object",
        "objects",
        "animal",
        "animals",
        "creature",
        "creatures",
        "character",
        "characters",
    }
)

_FRUIT_WORDS = frozenset(
    {
        "fruit",
        "fruits",
        "froot",
        "froots",
        "apple",
        "apples",
        "banana",
        "bananas",
        "orange",
        "oranges",
        "grape",
        "grapes",
        "strawberry",
        "strawberries",
        "watermelon",
        "pineapple",
        "mango",
        "peach",
        "pear",
        "lemon",
        "cherry",
        "berries",
    }
)

_NONHUMAN_SUBJECT = frozenset(
    {
        "dog",
        "cat",
        "bird",
        "horse",
        "robot",
        "dragon",
        "tiger",
        "lion",
        "wolf",
        "fox",
        "bear",
        "elephant",
        "car",
        "truck",
        "bike",
        "motorcycle",
        "airplane",
        "ship",
        "boat",
        "train",
        "toy",
        "toys",
        "object",
        "objects",
        "animal",
        "animals",
        "creature",
        "creatures",
        "vegetable",
        "vegetables",
        "tomato",
        "carrot",
        "food",
        "foods",
    }
) | _FRUIT_WORDS

_HUMAN_NEGATIVES_FOR_NONHUMAN = (
    "humans, people, woman, man, girl, boy, lady, guy, human figures, "
    "photorealistic people, human silhouettes, dark shadowy humans"
)
_COMMAND_WORDS = frozenset(
    {
        "make",
        "create",
        "generate",
        "draw",
        "design",
        "build",
        "please",
        "can",
        "you",
        "a",
        "an",
        "the",
        "of",
        "for",
        "about",
        "showing",
        "with",
        "in",
        "which",
        "where",
        "my",
        "me",
        "some",
        "this",
        "that",
        "video",
        "image",
        "picture",
        "photo",
        "illustration",
        "poster",
        "banner",
        "graphic",
        "reel",
        "clip",
        "mp4",
        "gif",
        "short",
        "long",
        "anime",
        "cartoon",
        "cinematic",
        "realistic",
        "photorealistic",
    }
)
_BRAND_OVERRIDE = re.compile(
    r"\b(veridiq|veridiq logo|wordmark|brand mark|company logo|office agents?)\b",
    re.I,
)


def status() -> dict[str, Any]:
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message="Free Pollinations image generation ready (Flux, no API key).",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        extra={"unlimited_soft": True, "cost": 0, "model": DEFAULT_MODEL},
    )


def test_connection() -> dict[str, Any]:
    try:
        r = requests.get(
            f"{BASE}/{quote('simple blue geometric test pattern')}",
            params={"width": 64, "height": 64, "nologo": "true", "model": "turbo"},
            timeout=30,
        )
        ok = r.status_code == 200 and (r.headers.get("content-type") or "").startswith("image/")
        return {
            "platform": PLATFORM,
            "status": "ok" if ok else "error",
            "ok": ok,
            "api_response_status": r.status_code,
            "message": "Pollinations image OK." if ok else f"HTTP {r.status_code}",
        }
    except Exception as exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": str(exc)[:200]}


def expand_user_typos(text: str) -> str:
    """Expand common typos / split words before subject lock (fruits talking…)."""
    p = (text or "").strip()
    # Multi-word / phrase fixes first
    replacements = (
        (r"\bthem\s+selved\b", "themselves"),
        (r"\bthem\s+selves\b", "themselves"),
        (r"\beach\s+ither\b", "each other"),
        (r"\bither\b", "each other"),
        (r"\bdecribing\b", "describing"),
        (r"\bdesribing\b", "describing"),
        (r"\bdescribng\b", "describing"),
        (r"\btalkin\b", "talking"),
        (r"\btalkng\b", "talking"),
        (r"\bfruts\b", "fruits"),
        (r"\bfruiits\b", "fruits"),
        (r"\bfroots\b", "fruits"),
        (r"\bfroot\b", "fruit"),
        (r"\bvidoe\b", "video"),
        (r"\bvedio\b", "video"),
        # Brand / image request typos (vridiq must be explicit — optional-e regex misses it)
        (r"\bvridiq\b", "veridiq"),
        (r"\bveridiqw\b", "veridiq"),
        (r"\bverdiq\b", "veridiq"),
        (r"\bveridq\b", "veridiq"),
        (r"\bveridig\b", "veridiq"),
        (r"\bverrdqiq\b", "veridiq"),
        (r"\bv[e]?rid[iq]g?\b", "veridiq"),

        (r"\bcreate\s+va\s+(imae|imag|imge|image|pic|picture|photo)\b", r"create a \1"),
        (r"\bmake\s+va\s+(imae|imag|imge|image|pic|picture|photo)\b", r"make a \1"),
        (r"\bgenerate\s+va\s+(imae|imag|imge|image|pic|picture|photo)\b", r"generate a \1"),
    )
    for pat, rep in replacements:
        p = re.sub(pat, rep, p, flags=re.I)
    return p


def clean_user_prompt(prompt: str) -> str:
    """Strip command wrappers; keep gender/age/identity and scene words intact."""
    p = expand_user_typos(prompt or "").strip()
    # "make a gym boy video" / "generate gym boy image of …" (incl. image typos)
    media = (
        r"images?|imgs?|imae|imag|imge|imgae|pics?|pictures?|pictur|photos?|phto|"
        r"illustrations?|poster|banner|graphic|videos?|reels?|clip|mp4|gif|drawings?"
    )
    p = re.sub(
        r"^(please\s+)?(can you\s+)?(create|generate|make|draw|design|build)\s+"
        r"(an?\s+)?(long\s+|short\s+)?"
        r"(?:(?P<subject>.+?)\s+)?"
        rf"({media})\s*"
        r"(for|of|about|showing|with|in which|where|:)?\s*",
        lambda m: (m.group("subject") or "").strip() + " ",
        p,
        flags=re.I,
    )
    # Leading media-type only: "video of gym boy" / "image: …" / "imae …"
    p = re.sub(
        rf"^(an?\s+)?(long\s+|short\s+)?({media})\s*"
        r"(for|of|about|showing|with|:)?\s*",
        "",
        p,
        flags=re.I,
    )
    # Trailing media-type: "gym boy video" / "… imae"
    p = re.sub(
        rf"\s+(long\s+|short\s+)?({media})\s*$",
        "",
        p,
        flags=re.I,
    )
    # Strip meta instructions like "not as text"
    p = re.sub(r"\b(not\s+as\s+text|as\s+(an?\s+)?image|no\s+text|visual\s+only)\b", "", p, flags=re.I)
    p = re.sub(r"\s+", " ", p).strip(" .,!?:;")
    # Never drop identity words if cleaning emptied the prompt
    if not p:
        return expand_user_typos(prompt or "").strip() or (prompt or "").strip()
    return p


_ANIMAL_DRIFT = frozenset(
    {
        "cat",
        "cats",
        "dog",
        "dogs",
        "kitten",
        "kittens",
        "puppy",
        "puppies",
        "pet",
        "pets",
        "animal",
        "animals",
        "kitty",
        "feline",
        "canine",
    }
)


def detect_subject_lock(prompt: str) -> dict[str, Any]:
    """Detect primary subject + gender anti-drift negatives from user text."""
    scene = clean_user_prompt(prompt)
    tokens = re.findall(r"[a-zA-Z']+", scene.lower())
    male = [t for t in tokens if t in _MALE]
    female = [t for t in tokens if t in _FEMALE]
    nouns = [t for t in tokens if t in _SUBJECT_NOUNS]
    fruit_hits = [t for t in tokens if t in _FRUIT_WORDS]
    nonhuman_hits = [t for t in tokens if t in _NONHUMAN_SUBJECT]
    animal_hits = [t for t in tokens if t in _ANIMAL_DRIFT]
    talking = bool(
        re.search(
            r"\b(talking|talk|speak|speaking|dialogue|convers|describe|describing|"
            r"introducing|themselves|each other)\b",
            scene,
            re.I,
        )
    )

    # Fruits/animals/objects talking → NEVER treat as gendered humans
    is_fruit = bool(fruit_hits) or bool(re.search(r"\bfruits?\b", scene, re.I))
    is_nonhuman = bool(nonhuman_hits) or is_fruit
    # Explicit human words can still win when user asked for people + fruit props
    explicit_human = any(
        t in tokens for t in ("boy", "girl", "man", "woman", "guy", "lady", "person", "people", "human")
    )
    if is_nonhuman and not (explicit_human and not is_fruit):
        male = []
        female = []

    gender: Optional[str] = None
    if male and not female:
        gender = "male"
    elif female and not male:
        gender = "female"

    # Build a short primary subject phrase from meaningful tokens
    keep: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9']+", scene):
        low = raw.lower()
        if low in _COMMAND_WORDS and low not in _MALE and low not in _FEMALE and low not in _SUBJECT_NOUNS:
            continue
        keep.append(raw)
        if len(keep) >= 8:
            break
    primary = " ".join(keep).strip() or scene[:120]

    # Prefer explicit gendered noun phrase when present (e.g. "gym boy")
    if gender == "male" and any(t in tokens for t in ("boy", "man", "guy", "male")):
        primary = scene[:160]
    elif gender == "female" and any(t in tokens for t in ("girl", "woman", "lady", "female")):
        primary = scene[:160]
    elif is_fruit:
        primary = (
            "cute anthropomorphic fruit characters (apple, banana, orange) with expressive "
            f"faces and mouths, talking and describing themselves: {scene[:120]}"
        )
    elif is_nonhuman and talking:
        primary = f"cute anthropomorphic characters based on {primary}: {scene[:140]}"

    negatives: list[str] = [
        "wrong gender",
        "gender swap",
        "logo",
        "watermark",
        "text overlay",
        "text gibberish",
        "global mush blur",
        "bad anatomy",
        "flicker",
        "distortion",
        "motion blur mush",
        "deformed limbs",
        "extra fingers",
        "low quality",
        "jpeg artifacts",
        "abstract blur",
        "abstract brand mark",
        "dark shadows",
        "blurry faces",
        "low-resolution",
        "pixelated",
        "oversaturated noise",
        "mud textures",
        "unrelated objects",
        "subject drift",
        "wrong subject",
    ]
    # Forbid animal drift unless the user asked for an animal
    if not animal_hits and not (is_nonhuman and any(t in tokens for t in _ANIMAL_DRIFT)):
        negatives.extend(
            [
                "cat",
                "dog",
                "kitten",
                "puppy",
                "pet animal",
                "random animal",
                "cute cat",
                "stock photo cat",
            ]
        )
    if is_nonhuman or is_fruit:
        negatives.extend(
            [
                "humans",
                "people",
                "woman",
                "man",
                "girl",
                "boy",
                "lady",
                "guy",
                "human figures",
                "photorealistic people",
                "human silhouettes",
                "dark shadowy humans",
                "god-ray pitch black garden with humans",
            ]
        )
    elif gender == "male":
        negatives.extend(
            [
                "woman",
                "girl",
                "female",
                "lady",
                "feminine face",
                "she",
                "her",
            ]
        )
    elif gender == "female":
        negatives.extend(
            [
                "man",
                "boy",
                "male",
                "guy",
                "masculine face",
                "he",
                "him",
            ]
        )

    concrete = bool(male or female or nouns or is_fruit or is_nonhuman) and not _is_brand_only_request(
        scene
    )
    return {
        "scene": scene,
        "primary_subject": primary,
        "gender": gender,
        "nouns": nouns[:8],
        "negatives": negatives,
        "concrete": concrete,
        "is_brand_request": _is_brand_only_request(scene),
        "is_fruit": is_fruit,
        "is_nonhuman": is_nonhuman,
        "talking_characters": bool(talking and (is_fruit or is_nonhuman)),
        "fruit_hits": fruit_hits[:8],
        "asks_animal": bool(animal_hits),
    }


def _is_brand_only_request(scene: str) -> bool:
    low = (scene or "").lower()
    if not low:
        return False
    # Explicit brand / product demo — allow VERIDIQ overlays
    brandish = any(
        w in low
        for w in (
            "veridiq",
            "verdiq",
            "veridig",
            "logo",
            "wordmark",
            "brand",
            "product demo",
            "platform tour",
            "dashboard",
            "our product",
            "agent workspace",
            "truth verification",
            "what is ver",
        )
    )
    # Concrete person/animal/object scene is NOT brand-only even if "veridiq" appears later
    tokens = set(re.findall(r"[a-zA-Z']+", low))
    has_person = bool(tokens & (_MALE | _FEMALE | {"person", "people", "human"}))
    has_thing = bool(tokens & (_SUBJECT_NOUNS - {"office", "desk", "agent", "agents"}))
    if has_person or has_thing:
        # "gym boy" etc. — concrete, not brand overlay
        if "veridiq" not in low and "logo" not in low and "verdiq" not in low:
            return False
        # User asked for a person scene — still concrete
        if has_person and any(t in tokens for t in ("boy", "girl", "man", "woman", "guy", "lady")):
            return False
    return brandish and not (has_person or has_thing)


def subject_locked_prompt(user_prompt: str, *, style: str = "photo", extra: str = "") -> str:
    """Public helper: final prompt with subject lock + quality + negatives."""
    return enrich_scene_prompt(user_prompt, style=style, extra=extra)


def enrich_scene_prompt(user_prompt: str, *, style: str = "photo", extra: str = "") -> str:
    """User subject stays PRIMARY — Gemini cinematic quality tags; no conflicting gender/brand bias."""
    from veridiq.postings.creative import (
        CFG_STEPS_PROMPT,
        NEGATIVE_PROMPT,
        QUALITY_ANCHOR_SENTENCE,
        STYLE_ANCHORS,
        FRUIT_SUBJECT_ANCHOR,
        BRIGHT_LIGHTING,
        CAMERA_PHYSICS_ANCHOR,
    )

    lock = detect_subject_lock(user_prompt)
    scene = lock["scene"]
    primary = lock["primary_subject"]
    gender = lock["gender"]
    is_fruit = bool(lock.get("is_fruit"))
    is_nonhuman = bool(lock.get("is_nonhuman"))
    talking = bool(lock.get("talking_characters"))

    # Gender-locked / subject-locked lead sentence (critical anti-drift)
    # ALWAYS lead with PRIMARY SUBJECT from the user topic — never omit.
    subject_lead = (primary or scene or "subject").strip()
    if is_fruit or (is_nonhuman and talking):
        lead = (
            f"PRIMARY SUBJECT (CRITICAL — never replace with humans or unrelated animals): {subject_lead}. "
            f"Exact scene: {scene}. "
            f"{FRUIT_SUBJECT_ANCHOR if is_fruit else 'cute anthropomorphic non-human characters with expressive faces and mouths, Pixar-quality, vibrant colors, bright well-lit'}."
        )
    elif gender == "male":
        lead = (
            f"PRIMARY SUBJECT (do not change gender): {subject_lead}. "
            f"Show a clearly male subject — a boy/man as described, photoreal facial details. "
            f"Exact scene: {scene}."
        )
    elif gender == "female":
        lead = (
            f"PRIMARY SUBJECT (do not change gender): {subject_lead}. "
            f"Show a clearly female subject — a girl/woman as described, photoreal facial details. "
            f"Exact scene: {scene}."
        )
    else:
        lead = (
            f"PRIMARY SUBJECT (CRITICAL — stay on topic, never replace with cat/dog/unrelated): "
            f"{subject_lead}. Exact scene: {scene}."
        )

    # Brand / office overlays ONLY when user asked for brand/office agents — never for gym boy etc.
    boost = ""
    low = scene.lower()
    if lock["is_brand_request"]:
        # Force VERIDIQ product visual language + hard animal negatives (anti cat/dog drift)
        lead = (
            "PRIMARY SUBJECT (CRITICAL — VERIDIQ brand product visual ONLY): "
            "VERIDIQ wordmark / AI truth-verification platform UI, modern dark dashboard, "
            f"never replace with animals or unrelated stock photos. Exact scene: {scene}."
        )
        lock_negs = list(lock.get("negatives") or [])
        for extra_neg in (
            "cat",
            "dog",
            "kitten",
            "puppy",
            "animal",
            "pet",
            "feline",
            "cute cat",
            "stock photo animal",
        ):
            if extra_neg not in lock_negs:
                lock_negs.append(extra_neg)
        lock = {**lock, "negatives": lock_negs, "primary_subject": "VERIDIQ"}
        primary = "VERIDIQ"
        if any(w in low for w in ("office", "desk", "desks", "workplace", "cubicle")):
            boost = (
                "modern open-plan office setting, professionals at desks with laptops, "
                "soft natural window light, subject tack-sharp, soft creamy background bokeh, "
            )
        if any(w in low for w in ("agent", "agents", "ai agent", "workforce")):
            boost += (
                "diverse AI workforce agents portrayed as realistic people at workstations, "
                "not robots, faces visible, "
            )
    elif any(w in low for w in ("office", "desk", "agent", "agents")) and not lock["concrete"]:
        boost = (
            "professional agent workspace, soft natural window light, warm-neutral grade, "
            "curved ultrawide Agent Workspace dashboard with green charts, "
            "subject tack-sharp, soft creamy background bokeh, cinematic commercial B-roll, "
        )

    # Gemini cinematic recipe: subject sharp + soft bg bokeh (not everything-in-focus)
    if is_fruit or (is_nonhuman and talking):
        quality = (
            f"{FRUIT_SUBJECT_ANCHOR if is_fruit else 'Pixar-quality anthropomorphic characters'}, "
            f"{BRIGHT_LIGHTING}, {CAMERA_PHYSICS_ANCHOR}, vibrant colorful set, {STYLE_ANCHORS}"
        )
        # Cartoon bias helps fruit characters stay non-human
        if style not in ("anime", "cgi"):
            style = "cartoon"
    elif style in ("cartoon", "poster"):
        quality = (
            "2D cartoon animation style, bold clean outlines, vibrant colors, "
            f"Pixar-inspired, storybook lighting, high detail, sharp edges, {STYLE_ANCHORS}"
        )
    elif style == "anime":
        quality = (
            "anime style illustration, vibrant colors, clean lineart, expressive characters, "
            f"high detail cel shading, {STYLE_ANCHORS}"
        )
    elif style == "cinematic":
        quality = f"cinematic still, filmic warm-neutral color grade, commercial B-roll, {STYLE_ANCHORS}"
    elif style in ("cgi", "3d"):
        quality = f"3D CGI render, octane render, detailed materials, {STYLE_ANCHORS}"
    else:
        quality = (
            f"highly detailed, detailed face, high resolution, 8k quality, realistic proportions, "
            f"{STYLE_ANCHORS}"
        )

    lock_negs = ", ".join(lock["negatives"][:28])
    neg = f"{NEGATIVE_PROMPT}, {lock_negs}"
    if is_fruit or is_nonhuman:
        neg = f"{neg}, {_HUMAN_NEGATIVES_FOR_NONHUMAN}"
        neg = (
            f"{neg}, collage, grid, tile, sheet of faces, contact sheet, multiple panels, "
            "meme, title card, poster with text, distorted faces, 4x4 grid, tiled collage"
        )
    elif gender == "male" and "woman" not in neg.lower():
        neg = f"{neg}, woman, girl, female, lady"
    elif gender == "female" and "man" not in neg.lower():
        neg = f"{neg}, man, boy, male, guy"
    extra_bit = f" {extra.strip()}." if (extra or "").strip() else ""
    # Style after subject — never before — so subject wins; bake CFG/steps + quality anchor
    single = (
        " ONE single clear subject centered, full scene, NOT a collage, NOT a grid of faces."
        if (is_fruit or is_nonhuman)
        else ""
    )
    full = (
        f"{lead} {boost}{quality}.{extra_bit}{single} "
        f"{CFG_STEPS_PROMPT}. {QUALITY_ANCHOR_SENTENCE} "
        f"Negative prompt: {neg}."
    )
    return full[:2200]


def _short_poll_err(raw: str) -> str:
    """Never surface giant Queue-full / HTML dumps to UX."""
    low = (raw or "").lower()
    if "429" in low or "queue full" in low or "max: 1" in low:
        return "Free image queue busy (rate limit). Wait a few seconds and retry."
    if "timeout" in low or "timed out" in low:
        return "Image request timed out. Retry."
    msg = re.sub(r"\s+", " ", (raw or "").strip())[:120]
    return msg or "Image generation failed. Retry."


def generate_image(
    *,
    prompt: str,
    width: int = 1280,
    height: int = 1280,
    filename_stem: str | None = None,
    style: str = "photo",
    model: Optional[str] = None,
    timeout: float = 45.0,
    seed: Optional[int] = None,
    enhance: bool = True,
    allow_turbo_retry: bool = True,
    max_attempts: int | None = None,
    backoff_sec: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    q = (prompt or "").strip()
    if not q:
        return {"status": "invalid_args", "ok": False, "message": "prompt is required."}

    lock = detect_subject_lock(q)
    full = enrich_scene_prompt(q, style=style)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "", (filename_stem or uuid.uuid4().hex)[:40]) or uuid.uuid4().hex[:12]
    # Unique file each run so browser cache doesn't show stale logos
    stem = f"{stem}_{uuid.uuid4().hex[:8]}"
    path = OUT_DIR / f"{stem}.jpg"
    mid = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    use_seed = int(seed if seed is not None else (time.time() * 1000) % 2_147_483_647)
    base_params = {
        "width": max(512, min(1280, int(width or 1280))),
        "height": max(512, min(1280, int(height or 1280))),
        "nologo": "true",
        "enhance": "true" if enhance else "false",
        "seed": use_seed,
        "guidance": 7.5,
        "cfg": 7.5,
        "steps": 40,
    }

    # Model rotation: requested → flux → turbo (deduped)
    models: list[str] = []
    for m in (mid, *FALLBACK_MODELS):
        if m and m not in models:
            models.append(m)
    if not allow_turbo_retry:
        models = [mid]

    attempts = int(max_attempts) if max_attempts is not None else (4 if allow_turbo_retry else 1)
    attempts = max(1, min(4, attempts))
    waits = backoff_sec if backoff_sec is not None else _RETRY_BACKOFF_SEC
    last_err = ""
    used_model = mid
    used_base = BASE

    try:
        # Serialize all Pollinations downloads (shared with video stills)
        with pollinations_slot():
            for attempt in range(attempts):
                if attempt > 0:
                    pause = waits[min(attempt - 1, len(waits) - 1)] if waits else 3.0
                    time.sleep(max(0.5, float(pause)))

                use_model = models[min(attempt, len(models) - 1)]
                use_base = ALT_BASES[min(attempt % len(ALT_BASES), len(ALT_BASES) - 1)]
                # On later attempts also flip model within the list
                if attempt >= len(models):
                    use_model = models[attempt % len(models)]
                params = {**base_params, "model": use_model}
                url = f"{use_base}/{quote(full)}"
                req_timeout = float(timeout or 45.0)
                if attempt > 0:
                    req_timeout = min(req_timeout, 22.0)

                try:
                    resp = requests.get(url, params=params, timeout=req_timeout)
                except Exception as exc:
                    last_err = _short_poll_err(str(exc))
                    continue

                ctype = (resp.headers.get("content-type") or "").lower()
                if resp.status_code == 429:
                    last_err = _short_poll_err(f"HTTP 429: {resp.text[:80]}")
                    continue
                if resp.status_code == 200 and "image" in ctype:
                    path.write_bytes(resp.content)
                    if path.stat().st_size < 2000:
                        last_err = "Downloaded image was too small / empty."
                        continue
                    used_model = use_model
                    used_base = use_base
                    rel = str(path.relative_to(_ROOT)).replace("\\", "/")
                    return {
                        "status": "ok",
                        "ok": True,
                        "provider": "pollinations_image",
                        "model": used_model,
                        "endpoint": used_base,
                        "prompt": full[:800],
                        "user_prompt": lock["scene"][:300],
                        "primary_subject": lock["primary_subject"][:200],
                        "gender_lock": lock["gender"],
                        "seed": use_seed,
                        "image_path": rel,
                        "image_url": f"/api/v1/veridiq/marketing/image/file/{path.name}",
                        "absolute_path": str(path),
                        "bytes": path.stat().st_size,
                        "width": params["width"],
                        "height": params["height"],
                        "attempts": attempt + 1,
                        "message": (
                            f"Image ready ({path.stat().st_size // 1024} KB, {used_model}) — "
                            f"subject: {lock['primary_subject'][:80]}"
                        ),
                    }
                last_err = _short_poll_err(f"HTTP {resp.status_code}: {resp.text[:80]}")
                if not allow_turbo_retry:
                    break

        return {
            "status": "error",
            "ok": False,
            "retry": True,
            "message": last_err or "Image busy — retry in a few seconds.",
        }
    except TimeoutError as exc:
        return {
            "status": "error",
            "ok": False,
            "retry": True,
            "message": _short_poll_err(str(exc)),
        }
    except Exception as exc:
        return {
            "status": "error",
            "ok": False,
            "retry": True,
            "message": _short_poll_err(str(exc)),
        }


def generate_images_parallel(
    prompts: list[str],
    *,
    width: int = 1280,
    height: int = 720,
    filename_prefix: str = "still",
    max_workers: int = 1,
    timeout: float = 45.0,
    style: str = "photo",
    seed: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Generate multiple images — serialized via global Pollinations semaphore."""
    if not prompts:
        return []
    results: list[Optional[dict[str, Any]]] = [None] * len(prompts)
    base_seed = seed if seed is not None else int(time.time() * 1000) % 2_147_483_647

    def _one(idx: int, pr: str) -> tuple[int, dict[str, Any]]:
        return idx, generate_image(
            prompt=pr,
            width=width,
            height=height,
            filename_stem=f"{filename_prefix}_{idx}",
            style=style,
            timeout=timeout,
            seed=(base_seed + idx * 17) % 2_147_483_647,
            model="turbo",
            max_attempts=3,
        )

    # workers=1 preferred; semaphore still serializes HTTP even if >1
    workers = 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, i, p) for i, p in enumerate(prompts)]
        for fut in as_completed(futs):
            try:
                idx, res = fut.result()
                results[idx] = res
            except Exception as exc:
                _ = exc
    return [r for r in results if isinstance(r, dict)]
