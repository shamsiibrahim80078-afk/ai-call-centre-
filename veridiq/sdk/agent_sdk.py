"""Universal VERIDIQ Agent SDK — inter-agent tasks, memory, tools, progress."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database import db_session, initialize_database
from memory.memory_manager import MemoryManager
from scheduler.event_bus import global_event_bus

_SHARED_NS = "veridiq-shared-memory"
_sdk_lock = threading.RLock()
_instances: dict[str, "AgentSDK"] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_sdk(agent_type: str) -> "AgentSDK":
    key = (agent_type or "system").strip()
    with _sdk_lock:
        if key not in _instances:
            _instances[key] = AgentSDK(agent_type=key)
        return _instances[key]


class AgentSDK:
    """Per-agent communication handle. All agents should use this instead of
    hardcoded cross-agent calls or direct third-party wiring."""

    def __init__(self, agent_type: str) -> None:
        initialize_database()
        self.agent_type = (agent_type or "system").strip()
        self.agent_uuid = f"sdk:{self.agent_type}"
        self._memory = MemoryManager(default_agent_uuid=self.agent_uuid)
        self._shared = MemoryManager(default_agent_uuid=_SHARED_NS)

    # ------------------------------------------------------------------ tasks

    def sendTask(
        self,
        to_agent: str,
        task: dict[str, Any] | str,
        *,
        priority: int = 100,
        execute: bool = False,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Queue a task for another agent. Optionally start execution via the worker pool."""
        to_agent = (to_agent or "").strip()
        if not to_agent:
            raise ValueError("to_agent is required")
        payload = task if isinstance(task, dict) else {"instruction": str(task)}
        task_id = str(uuid.uuid4())
        stamped = _utc_now()
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO veridiq_sdk_tasks
                    (task_id, from_agent, to_agent, payload_json, status, priority,
                     job_id, progress, confidence, result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, 0.0, NULL, NULL, NULL, ?, ?)
                """,
                (
                    task_id,
                    self.agent_type,
                    to_agent,
                    json.dumps(payload, default=str)[:50000],
                    int(priority),
                    job_id,
                    stamped,
                    stamped,
                ),
            )
        event = global_event_bus.emit(
            "sdk.task.sent",
            {
                "task_id": task_id,
                "from_agent": self.agent_type,
                "to_agent": to_agent,
                "priority": priority,
            },
            source=f"sdk:{self.agent_type}",
        )
        result: dict[str, Any] = {
            "ok": True,
            "task_id": task_id,
            "from_agent": self.agent_type,
            "to_agent": to_agent,
            "status": "queued",
            "event_uuid": event.get("event_uuid"),
            "created_at": stamped,
        }
        if execute:
            result["execution"] = self._execute_queued(task_id, to_agent, payload, job_id=job_id)
        return result

    def receiveTask(self, *, limit: int = 10, claim_only: bool = True) -> dict[str, Any]:
        """Pull inbox tasks addressed to this agent."""
        limit = max(1, min(100, int(limit)))
        with db_session() as conn:
            if claim_only:
                rows = conn.execute(
                    """
                    SELECT * FROM veridiq_sdk_tasks
                    WHERE to_agent = ? AND status = 'queued'
                    ORDER BY priority ASC, id ASC
                    LIMIT ?
                    """,
                    (self.agent_type, limit),
                ).fetchall()
                claimed = []
                stamped = _utc_now()
                for row in rows:
                    conn.execute(
                        """
                        UPDATE veridiq_sdk_tasks
                        SET status = 'claimed', updated_at = ?
                        WHERE task_id = ? AND status = 'queued'
                        """,
                        (stamped, row["task_id"]),
                    )
                    item = dict(row)
                    item["status"] = "claimed"
                    item["payload"] = json.loads(item.pop("payload_json") or "{}")
                    item.pop("result_json", None)
                    claimed.append(item)
                return {"ok": True, "agent_type": self.agent_type, "count": len(claimed), "tasks": claimed}
            rows = conn.execute(
                """
                SELECT * FROM veridiq_sdk_tasks
                WHERE to_agent = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self.agent_type, limit),
            ).fetchall()
        tasks = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            if item.get("result_json"):
                try:
                    item["result"] = json.loads(item.pop("result_json"))
                except (json.JSONDecodeError, TypeError):
                    item["result"] = item.pop("result_json")
            else:
                item.pop("result_json", None)
            tasks.append(item)
        return {"ok": True, "agent_type": self.agent_type, "count": len(tasks), "tasks": tasks}

    def askAgent(
        self,
        to_agent: str,
        question: dict[str, Any] | str,
        *,
        timeout_sec: float = 60.0,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a task and wait for synchronous execution via the worker pool.

        Execution is blocking through ``run_agent_task``; ``timeout_sec`` is recorded
        for clients and used as a soft deadline hint in the response metadata.
        """
        import time as _time

        started = _time.perf_counter()
        payload = question if isinstance(question, dict) else {"instruction": str(question), "ask": True}
        sent = self.sendTask(to_agent, payload, execute=True, job_id=job_id)
        execution = sent.get("execution") or {}
        elapsed = _time.perf_counter() - started
        timed_out = elapsed > float(timeout_sec)
        return {
            "ok": bool(execution.get("ok", execution.get("envelope", {}).get("ok"))) and not timed_out,
            "task_id": sent.get("task_id"),
            "from_agent": self.agent_type,
            "to_agent": to_agent,
            "answer": execution.get("envelope") or execution,
            "timeout_sec": timeout_sec,
            "elapsed_sec": round(elapsed, 3),
            "timed_out": timed_out,
        }

    def processInbox(self, *, limit: int = 5, execute: bool = True) -> dict[str, Any]:
        """Claim queued tasks addressed to this agent and optionally execute them."""
        claimed = self.receiveTask(limit=limit, claim_only=True)
        results = []
        for task in claimed.get("tasks") or []:
            task_id = task.get("task_id")
            payload = task.get("payload") or {}
            if not execute:
                results.append({"task_id": task_id, "status": "claimed"})
                continue
            try:
                from veridiq.agents import get_agent

                envelope = get_agent(self.agent_type).run(
                    {**payload, "_sdk_task_id": task_id},
                    job_id=task_id,
                )
                if isinstance(envelope, dict) and envelope.get("ok"):
                    self.completeTask(task_id, result=envelope, confidence=envelope.get("confidence"))
                else:
                    self.completeTask(
                        task_id,
                        result=envelope if isinstance(envelope, dict) else {},
                        error=(envelope or {}).get("error") if isinstance(envelope, dict) else "failed",
                    )
                results.append({"task_id": task_id, "ok": bool(isinstance(envelope, dict) and envelope.get("ok")), "envelope": envelope})
            except Exception as exc:
                self.completeTask(task_id, error=str(exc)[:400])
                results.append({"task_id": task_id, "ok": False, "error": str(exc)[:400]})
        return {
            "ok": True,
            "agent_type": self.agent_type,
            "claimed": claimed.get("count", 0),
            "results": results,
        }

    # ----------------------------------------------------------------- memory

    def shareMemory(
        self,
        key: str,
        value: Any = None,
        *,
        scope: str = "shared",
        tags: Optional[list[str]] = None,
        load_only: bool = False,
    ) -> dict[str, Any]:
        """Read/write shared or private agent memory."""
        store = self._shared if scope == "shared" else self._memory
        tag_list = list(tags or []) + ["sdk", scope, self.agent_type]
        if load_only or value is None and not tags:
            loaded = store.load_memory(key, default=None)
            return {
                "ok": True,
                "action": "load",
                "scope": scope,
                "key": key,
                "value": loaded,
                "agent_type": self.agent_type,
            }
        if value is None:
            loaded = store.load_memory(key, default=None)
            return {"ok": True, "action": "load", "scope": scope, "key": key, "value": loaded}
        saved = store.save_memory(key, value, tags=tag_list)
        global_event_bus.emit(
            "sdk.memory.shared",
            {"key": key, "scope": scope, "from_agent": self.agent_type},
            source=f"sdk:{self.agent_type}",
        )
        return {"ok": True, "action": "save", "scope": scope, "key": key, "record": saved}

    # ------------------------------------------------------------------ tools

    def executeTool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        from veridiq.sdk.tools import execute_tool

        result = execute_tool(tool_name, **kwargs)
        global_event_bus.emit(
            "sdk.tool.executed",
            {"tool": tool_name, "ok": result.get("ok"), "from_agent": self.agent_type},
            source=f"sdk:{self.agent_type}",
        )
        return result

    # --------------------------------------------------------------- streaming

    def streamOutput(
        self,
        chunk: Any,
        *,
        task_id: Optional[str] = None,
        stream_id: Optional[str] = None,
        done: bool = False,
    ) -> dict[str, Any]:
        stream_id = stream_id or str(uuid.uuid4())
        stamped = _utc_now()
        payload = chunk if isinstance(chunk, dict) else {"text": str(chunk)}
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO veridiq_sdk_streams
                    (stream_id, agent_type, task_id, chunk_json, done, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    stream_id,
                    self.agent_type,
                    task_id,
                    json.dumps(payload, default=str)[:20000],
                    1 if done else 0,
                    stamped,
                ),
            )
        global_event_bus.emit(
            "sdk.stream.chunk",
            {
                "stream_id": stream_id,
                "agent_type": self.agent_type,
                "task_id": task_id,
                "done": done,
                "chunk": payload,
            },
            source=f"sdk:{self.agent_type}",
        )
        return {"ok": True, "stream_id": stream_id, "done": done, "created_at": stamped}

    def reportProgress(
        self,
        *,
        task_id: Optional[str] = None,
        progress: float = 0.0,
        stage: Optional[str] = None,
        confidence: Optional[float] = None,
        eta_sec: Optional[float] = None,
        message: Optional[str] = None,
        logs: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        progress = max(0.0, min(1.0, float(progress)))
        stamped = _utc_now()
        if task_id:
            with db_session() as conn:
                conn.execute(
                    """
                    UPDATE veridiq_sdk_tasks
                    SET progress = ?, confidence = COALESCE(?, confidence),
                        status = CASE WHEN status IN ('queued', 'claimed') THEN 'running' ELSE status END,
                        updated_at = ?
                    WHERE task_id = ?
                    """,
                    (progress, confidence, stamped, task_id),
                )
        try:
            from veridiq.workforce.pool import global_worker_pool

            global_worker_pool.set_agent_stage(
                self.agent_type,
                stage=stage or "sdk_progress",
                progress=progress,
                task=message,
            )
        except Exception:
            pass
        global_event_bus.emit(
            "sdk.progress",
            {
                "agent_type": self.agent_type,
                "task_id": task_id,
                "progress": progress,
                "stage": stage,
                "confidence": confidence,
                "eta_sec": eta_sec,
                "message": message,
                "logs": (logs or [])[:20],
            },
            source=f"sdk:{self.agent_type}",
        )
        return {
            "ok": True,
            "agent_type": self.agent_type,
            "task_id": task_id,
            "progress": progress,
            "stage": stage,
            "confidence": confidence,
            "eta_sec": eta_sec,
            "updated_at": stamped,
        }

    def completeTask(
        self,
        task_id: str,
        *,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> dict[str, Any]:
        if not task_id:
            raise ValueError("task_id is required")
        stamped = _utc_now()
        status = "failed" if error else "completed"
        with db_session() as conn:
            conn.execute(
                """
                UPDATE veridiq_sdk_tasks
                SET status = ?, result_json = ?, error = ?, confidence = COALESCE(?, confidence),
                    progress = CASE WHEN ? = 'completed' THEN 1.0 ELSE progress END,
                    updated_at = ?, finished_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    json.dumps(result or {}, default=str)[:50000],
                    error,
                    confidence,
                    status,
                    stamped,
                    stamped,
                    task_id,
                ),
            )
        global_event_bus.emit(
            "sdk.task.completed",
            {
                "task_id": task_id,
                "agent_type": self.agent_type,
                "status": status,
                "confidence": confidence,
            },
            source=f"sdk:{self.agent_type}",
        )
        return {
            "ok": error is None,
            "task_id": task_id,
            "status": status,
            "finished_at": stamped,
            "result": result,
            "error": error,
        }

    # --------------------------------------------------------------- internals

    def _execute_queued(
        self,
        task_id: str,
        to_agent: str,
        payload: dict[str, Any],
        *,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from veridiq.agents import AGENT_REGISTRY, get_agent
        from veridiq.workforce import control as agent_control

        if to_agent not in AGENT_REGISTRY:
            err = f"Unknown agent_type '{to_agent}'"
            self.completeTask(task_id, error=err)
            return {"ok": False, "error": err}
        try:
            agent_control.assert_runnable(to_agent)
        except agent_control.AgentStoppedError as exc:
            self.completeTask(task_id, error=str(exc))
            return {"ok": False, "error": str(exc), "status": exc.status}

        run_payload = {**payload, "_sdk_task_id": task_id, "_from_agent": self.agent_type}
        stamped = _utc_now()
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_sdk_tasks SET status = 'running', updated_at = ? WHERE task_id = ?",
                (stamped, task_id),
            )

        # Run inline (not via worker pool) so CEO→Director→Worker cascades cannot
        # deadlock the ThreadPoolExecutor when nested execute=True calls stack.
        try:
            envelope = get_agent(to_agent).run(run_payload, job_id=job_id or task_id)
            conf = envelope.get("confidence") if isinstance(envelope, dict) else None
            if isinstance(envelope, dict) and envelope.get("ok"):
                self.completeTask(task_id, result=envelope, confidence=conf)
            else:
                self.completeTask(
                    task_id,
                    result=envelope if isinstance(envelope, dict) else {"raw": envelope},
                    error=(envelope or {}).get("error") if isinstance(envelope, dict) else "execution_failed",
                    confidence=conf,
                )
            return {"ok": bool(isinstance(envelope, dict) and envelope.get("ok")), "envelope": envelope}
        except Exception as exc:
            self.completeTask(task_id, error=str(exc)[:500])
            return {"ok": False, "error": str(exc)[:500]}
