"""Unit tests for zero-cost free_media_pipeline (no network required for prompt tests)."""

from __future__ import annotations


def test_enhance_crypto_prompt_injects_neon_4k_cinematic():
    from veridiq.postings.free_media_pipeline import enhance_crypto_prompt

    out = enhance_crypto_prompt("Bitcoin rally")
    lower = out.lower()
    assert "bitcoin rally" in lower
    assert "neon" in lower or "neon-glow" in lower
    assert "4k" in lower
    assert "cinematic" in lower
    assert "crypto" in lower


def test_enhance_crypto_prompt_empty_fallback():
    from veridiq.postings.free_media_pipeline import enhance_crypto_prompt

    out = enhance_crypto_prompt("   ")
    lower = out.lower()
    assert "4k" in lower
    assert "neon" in lower or "neon-glow" in lower


def test_run_pipeline_importable():
    from veridiq.postings.free_media_pipeline import (
        build_video,
        enhance_crypto_prompt,
        generate_image,
        generate_images,
        generate_voiceover,
        run_pipeline,
    )

    assert callable(run_pipeline)
    assert callable(enhance_crypto_prompt)
    assert callable(generate_image)
    assert callable(generate_images)
    assert callable(generate_voiceover)
    assert callable(build_video)
