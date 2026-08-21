"""Tests for Mira feedback store + apply_learned_quality (learning loop)."""

from __future__ import annotations

import json
from pathlib import Path


def test_record_feedback_and_stats(tmp_path, monkeypatch):
    import database
    from veridiq.postings.learning import quality, store

    db = tmp_path / "learn.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    cfg = tmp_path / "mira_learning_config.json"
    monkeypatch.setattr(quality, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(store, "REF_DIR", tmp_path / "references")

    database.initialize_database(db)
    store.ensure_learning_tables()

    up = store.record_feedback(
        prompt="cinematic gym boy lifting weights, sharp focus",
        style="cinematic",
        media_url="/api/v1/fake.png",
        rating=5,
        chat_id="chat1",
        topic="gym boy lifting weights",
        media_type="image",
    )
    assert up["ok"] is True
    assert up["rating"] == 5

    down = store.record_feedback(
        prompt="muddy blurry mess",
        thumbs="down",
        media_url="/api/v1/bad.png",
        rating=3,
        topic="muddy blurry mess",
    )
    assert down["rating"] == 1

    stats = quality.feedback_stats()
    assert stats["ok"] is True
    assert stats["rated_examples"] >= 2
    assert "not" in stats["learning_note"].lower() or "scraping" in stats["learning_note"].lower()
    assert cfg.is_file()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["kind"] == "mira_learning_adapter"
    assert data["rated_examples"] >= 2


def test_apply_learned_quality_injects_anchors(tmp_path, monkeypatch):
    import database
    from veridiq.postings.learning import quality, store

    db = tmp_path / "learn2.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    cfg = tmp_path / "mira_learning_config.json"
    monkeypatch.setattr(quality, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(store, "REF_DIR", tmp_path / "references")

    database.initialize_database(db)
    store.ensure_learning_tables()

    store.record_feedback(
        prompt="photoreal gym athlete lifting barbell, studio lighting",
        style="photo",
        media_url="/x.png",
        rating=5,
        topic="gym athlete lifting barbell",
    )
    store.record_feedback(
        prompt="blurry dark noise",
        thumbs="down",
        media_url="/y.png",
        rating=1,
        topic="blurry dark noise",
    )

    out = quality.apply_learned_quality(
        "Create a gym boy lifting weights at gym",
        topic="gym boy lifting weights",
    )
    assert "Create a gym boy" in out or "gym" in out.lower()
    assert "past successes" in out.lower() or "preferred style" in out.lower() or "photo" in out.lower()
    assert len(out) >= len("Create a gym boy lifting weights at gym")


def test_apply_learned_quality_noop_without_data(tmp_path, monkeypatch):
    import database
    from veridiq.postings.learning import quality, store

    db = tmp_path / "empty.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    cfg = tmp_path / "mira_learning_config.json"
    monkeypatch.setattr(quality, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(store, "REF_DIR", tmp_path / "references")
    # Ensure empty adapter
    quality.save_learning_config(dict(quality.DEFAULT_CONFIG))

    database.initialize_database(db)
    store.ensure_learning_tables()

    prompt = "simple cinematic landscape"
    out = quality.apply_learned_quality(prompt, topic="landscape")
    # Without ratings/refs, should stay close to original
    assert out.startswith("simple cinematic landscape")


def test_brand_reference_register(tmp_path, monkeypatch):
    import database
    from veridiq.postings.learning import store

    db = tmp_path / "refs.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    ref_dir = tmp_path / "references"
    monkeypatch.setattr(store, "REF_DIR", ref_dir)

    database.initialize_database(db)
    store.ensure_learning_tables()

    src = tmp_path / "logo.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    meta = store.register_brand_reference(
        path=str(src),
        topic="VERIDIQ logo",
        tags=["brand"],
        source="upload",
        description="Brand mark",
    )
    assert meta["ok"] is True
    assert Path(meta["path"]).is_file()
    refs = store.list_references(topic="VERIDIQ")
    assert len(refs) >= 1


def test_apply_learned_quality_without_unsplash(tmp_path, monkeypatch):
    """Learning works with UNSPLASH_ACCESS_KEY set — Unsplash is never called."""
    import database
    from veridiq.postings.learning import quality, references, store

    db = tmp_path / "no_unsplash.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    cfg = tmp_path / "mira_learning_config.json"
    monkeypatch.setattr(quality, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(store, "REF_DIR", tmp_path / "references")
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fake-key-must-be-ignored")

    database.initialize_database(db)
    store.ensure_learning_tables()

    store.record_feedback(
        prompt="sharp cinematic product shot, soft key light",
        style="cinematic",
        media_url="/z.png",
        rating=5,
        topic="product shot soft light",
    )

    assert references.unsplash_configured() is False
    skipped = references.fetch_unsplash_references("anything", per_page=2, save=True)
    assert skipped["ok"] is False
    assert skipped.get("status") == "disabled"
    assert skipped.get("unsplash") is False
    assert skipped.get("cost") == "free"

    # Guard: if learning ever tried HTTP for Unsplash, fail hard
    import sys

    class _NoNet:
        def get(self, *a, **k):
            raise AssertionError("network must not be used for Unsplash")

    monkeypatch.setitem(sys.modules, "requests", _NoNet())

    out = quality.apply_learned_quality(
        "Create a product shot with soft light",
        topic="product shot soft light",
    )
    assert "Create a product shot" in out or "product" in out.lower()
    assert len(out) >= len("Create a product shot with soft light")

    st = quality.learning_status()
    assert st["unsplash"] is False
    assert st["unsplash_configured"] is False
    assert st["learning_sources"] == ["ratings", "uploads"]
    assert st["cost"] == "free"
    assert "no Unsplash" in (st["message"] or "") or "free" in (st["message"] or "").lower()

