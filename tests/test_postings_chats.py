"""Unit tests — Mira Postings chat persistence (SQLite + video_url)."""

from __future__ import annotations

import uuid


def test_postings_chat_save_load_with_video_url(tmp_path, monkeypatch):
    """Create chat, append user + assistant with video_url, reload full thread."""
    import database
    from veridiq.postings import chats

    db_file = tmp_path / f"postings_chats_{uuid.uuid4().hex[:8]}.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.initialize_database(db_file)

    created = chats.create_chat(title="")
    assert created["ok"] is True
    chat_id = created["chat_id"]
    assert created["title"] == "New chat"

    user = chats.append_message(
        chat_id,
        role="user",
        text="Make a gym boy video",
        set_title_from_text=True,
    )
    assert user["ok"] is True
    assert user.get("title") == "Make a gym boy video"

    video_url = "/api/v1/veridiq/marketing/video/file/demo_gym.mp4"
    action = {
        "action": "create_video",
        "status": "ok",
        "video_url": video_url,
        "render": {"video_url": video_url, "format": "mp4", "duration_sec": 15},
        "message": "Video ready.",
    }
    assistant = chats.append_assistant_from_action(
        chat_id,
        reply="Your gym boy video is ready.",
        action=action,
    )
    assert assistant["ok"] is True
    msg = assistant["message"]
    assert msg["role"] == "assistant"
    assert msg["video_url"] == video_url
    assert msg["text"]

    loaded = chats.get_chat(chat_id)
    assert loaded["ok"] is True
    assert loaded["title"] == "Make a gym boy video"
    assert loaded["count"] == 2
    roles = [m["role"] for m in loaded["messages"]]
    assert roles == ["user", "assistant"]
    assert loaded["messages"][1]["video_url"] == video_url
    assert loaded["messages"][1]["meta"]["action"] == "create_video"

    listed = chats.list_chats()
    assert listed["ok"] is True
    assert any(c["chat_id"] == chat_id for c in listed["chats"])

    deleted = chats.delete_chat(chat_id)
    assert deleted["ok"] is True
    missing = chats.get_chat(chat_id)
    assert missing["ok"] is False


def test_append_turn_from_agent_result_sync_image(tmp_path, monkeypatch):
    import database
    from veridiq.postings import chats

    db_file = tmp_path / f"postings_img_{uuid.uuid4().hex[:8]}.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.initialize_database(db_file)

    chat_id = chats.create_chat()["chat_id"]
    image_url = "/api/v1/veridiq/marketing/image/file/demo.png"
    result = {
        "ok": True,
        "intent": "create_image",
        "reply": "Image ready.",
        "action": {
            "action": "create_image",
            "status": "ok",
            "image_url": image_url,
            "message": "Image ready.",
        },
    }
    out = chats.append_turn_from_agent_result(
        chat_id,
        user_text="Generate an image of a gym boy",
        result=result,
    )
    assert out["ok"] is True
    loaded = chats.get_chat(chat_id)
    assert loaded["count"] == 2
    assert loaded["messages"][1]["image_url"] == image_url
    assert "gym boy" in loaded["title"].lower()
