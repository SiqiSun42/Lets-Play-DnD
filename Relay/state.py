"""dsh2server 协议的服务端状态。

设计要点（见 spec §6 P4）：
-实例状态保存在**内存**中。协议允许服务器无状态：进程重启后实例会自动重连并重推。
- 只有 **key 白名单**需要持久化。生产环境应接入 ``account.db``；这里用一个可替换的
  ``KeyStore`` 接口，默认实现是 JSON 文件，便于本地验收。
- **必须单进程**：状态在内存里，多 worker 会让同一实例落到不同进程。
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import (
    DEFAULT_TOPICS,
    EVENT_RING_LIMIT,
    F_EVENT,
    F_HELLO_ACK,
    HEARTBEAT_MS,
    INBOX_LIMIT,
    POLL_MAX_MS,
    PROTOCOL_VERSION,
    RETENTION_SECONDS,
    STALE_AFTER_SECONDS,
    fingerprint,
    frame,
)


# ─────────────────────────────── key 白名单 ───────────────────────────────


class JsonKeyStore:
    """key 白名单的 JSON 文件实现。开发与本地验收用。"""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._keys: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("keys") if isinstance(data, dict) else None
        if isinstance(entries, list):
            self._keys = [e for e in entries if isinstance(e, dict) and e.get("key")]

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"keys": self._keys}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def authorize(self, key: str) -> dict | None:
        """恒定时间比较；返回命中的条目或 None。"""
        if not key:
            return None
        with self._lock:
            for entry in self._keys:
                if hmac.compare_digest(str(entry.get("key", "")), key):
                    return entry
        return None

    def add(self, key: str, label: str | None = None,
            instance_id: str | None = None) -> dict:
        with self._lock:
            for entry in self._keys:
                if hmac.compare_digest(str(entry.get("key", "")), key):
                    return entry
            entry = {
                "key": key,
                "label": label,
                "instanceId": instance_id,
                "addedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._keys.append(entry)
            self._save()
            return entry

    def remove(self, key: str) -> bool:
        with self._lock:
            keep = [e for e in self._keys
                    if not hmac.compare_digest(str(e.get("key", "")), key)]
            removed = len(keep) != len(self._keys)
            self._keys = keep
            if removed:
                self._save()
            return removed

    def list_public(self) -> list[dict]:
        """供管理接口展示：只给指纹，不给完整 key。"""
        with self._lock:
            return [
                {
                    "fingerprint": fingerprint(str(e.get("key", ""))),
                    "label": e.get("label"),
                    "instanceId": e.get("instanceId"),
                    "addedAt": e.get("addedAt"),
                }
                for e in self._keys
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._keys)


# 兼容旧名（本地验收脚本用它）。
KeyStore = JsonKeyStore


class SqliteKeyStore:
    """key 白名单的 SQLite 实现，指向应用已有的 ``account.db``。

    表 ``dsh_instances`` 由本类负责创建。``username`` 记录实例归属，供中转
    服务器做「用户只能访问自己的实例」的校验（spec §8 约束 6）。
    """

    DDL = """
        CREATE TABLE IF NOT EXISTS dsh_instances (
          key         TEXT PRIMARY KEY,
          instance_id TEXT,
          username    TEXT,
          label       TEXT,
          created_at  TEXT NOT NULL
        )
    """

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(self.DDL)
            conn.commit()
        finally:
            conn.close()

    def authorize(self, key: str) -> dict | None:
        """按 key 命中后用恒定时间比较确认。"""
        if not key:
            return None
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM dsh_instances WHERE key = ?", (key,)
                ).fetchone()
            finally:
                conn.close()
        if row is None or not hmac.compare_digest(str(row["key"]), key):
            return None
        return {
            "key": row["key"],
            "instanceId": row["instance_id"],
            "username": row["username"],
            "label": row["label"],
        }

    def add(self, key: str, label=None, instance_id=None, username=None) -> dict:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO dsh_instances"
                    " (key, instance_id, username, label, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (key, instance_id, username, label, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM dsh_instances WHERE key = ?", (key,)
                ).fetchone()
            finally:
                conn.close()
        return {
            "key": key,
            "instanceId": row["instance_id"] if row else instance_id,
            "username": row["username"] if row else username,
            "label": row["label"] if row else label,
        }

    def remove(self, key: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM dsh_instances WHERE key = ?", (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def list_public(self) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM dsh_instances ORDER BY created_at"
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "fingerprint": fingerprint(str(r["key"])),
                "label": r["label"],
                "instanceId": r["instance_id"],
                "username": r["username"],
                "addedAt": r["created_at"],
            }
            for r in rows
        ]

    def __len__(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                return int(
                    conn.execute("SELECT COUNT(*) AS n FROM dsh_instances")
                    .fetchone()["n"]
                )
            finally:
                conn.close()


# ─────────────────────────────── 实例状态 ───────────────────────────────


@dataclass
class Instance:
    instance_id: str
    key_fingerprint: str | None = None
    label: str | None = None
    username: str | None = None
    transport: str = "http"
    tls: bool = False
    connected_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    disconnected_at: float | None = None
    hello: dict | None = None
    capabilities: dict = field(default_factory=dict)
    subscriptions: dict = field(
        default_factory=lambda: {"topics": [], "sessions": [], "assistantStreams": []}
    )
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_RING_LIMIT))
    inbox: deque = field(default_factory=lambda: deque(maxlen=INBOX_LIMIT))
    responses: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    last_seq: int = 0
    cursor: int = 0
    resync_needed: bool = False


class UnknownInstance(Exception):
    pass


class RequestTimeout(Exception):
    pass


class RelayState:
    def __init__(self, keystore: KeyStore | None = None,
                 event_limit: int = EVENT_RING_LIMIT,
                 inbox_limit: int = INBOX_LIMIT,
                 stale_after_seconds: float = STALE_AFTER_SECONDS,
                 retention_seconds: float = RETENTION_SECONDS):
        self.keys = keystore if keystore is not None else KeyStore()
        self.event_limit = event_limit
        self.inbox_limit = inbox_limit
        self.stale_after_seconds = stale_after_seconds
        self.retention_seconds = retention_seconds
        self.instances: dict[str, Instance] = {}
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)

    # ── 活跃度 ──────────────────────────────────────────────────

    def _online(self, inst: Instance, now: float) -> bool:
        """有 bye 则离线；否则按 lastSeenAt 的新鲜度判定。"""
        if inst.disconnected_at is not None:
            return False
        return (now - inst.last_seen_at) < self.stale_after_seconds

    def _prune_locked(self, now: float) -> None:
        """回收离线过久的实例，避免僵尸记录无限累积。"""
        deadline = now - self.retention_seconds
        gone = [iid for iid, inst in self.instances.items()
                if not self._online(inst, now) and inst.last_seen_at < deadline]
        for iid in gone:
            del self.instances[iid]

    # ── 上行：插件 → 服务器 ──────────────────────────────────────

    def ingest(self, instance_id: str, key_entry: dict, frames: list,
               transport: str = "http", tls: bool = False) -> int:
        """处理一批上行帧，返回已接受的最大事件 seq。"""
        with self.cond:
            self._prune_locked(time.time())
            inst = self.instances.get(instance_id)
            if inst is None:
                inst = Instance(instance_id=instance_id)
                self.instances[instance_id] = inst
            if key_entry:
                inst.key_fingerprint = fingerprint(str(key_entry.get("key", "")))
                inst.label = key_entry.get("label") or inst.label
                inst.username = key_entry.get("username") or inst.username
            inst.transport = transport
            inst.tls = tls
            inst.last_seen_at = time.time()
            inst.disconnected_at = None

            max_seq = inst.last_seq
            for f in frames:
                if not isinstance(f, dict):
                    continue
                kind = f.get("type")
                if kind == "hello":
                    self._on_hello(inst, f)
                elif kind == F_EVENT:
                    max_seq = max(max_seq, self._on_event(inst, f))
                elif kind == "response":
                    self._on_response(inst, f)
                elif kind == "ping":
                    self._queue_locked(inst, frame("pong", ts=int(time.time() * 1000)))
                elif kind == "ack":
                    inst.cursor = max(inst.cursor, int(f.get("seq") or 0))
                elif kind == "bye":
                    # 标记而非删除：紧接其后的重连会与删除抢跑。
                    inst.disconnected_at = time.time()
            self.cond.notify_all()
            return max_seq

    def _on_hello(self, inst: Instance, f: dict) -> None:
        inst.hello = {
            "v": f.get("v"),
            "lastSeq": f.get("lastSeq") or 0,
            "resumeFromSeq": f.get("resumeFromSeq") or 0,
            "subscriptions": f.get("subscriptions"),
        }
        inst.capabilities = f.get("capabilities") or {}
        info = f.get("instance") or {}
        if isinstance(info, dict) and info.get("displayName") and not inst.label:
            inst.label = info["displayName"]

        # 补发水位：从本地事件环推导服务器实际持有的最大 seq。
        resume_from = max((int(e.get("seq") or 0) for e in inst.events), default=0)
        self._queue_locked(inst, frame(
            F_HELLO_ACK,
            instanceId=inst.instance_id,
            serverTime=int(time.time() * 1000),
            heartbeatMs=HEARTBEAT_MS,
            resumeFromSeq=resume_from,
            serverSeq=inst.cursor,
            pollWaitMs=POLL_MAX_MS,
        ))
        # 默认订阅：全局主题；逐会话订阅由管理接口按需发起。
        self._queue_locked(inst, frame(
            "subscribe",
            id="sub-init",
            topics=list(DEFAULT_TOPICS),
            snapshot=True,
        ))

    def _on_event(self, inst: Instance, f: dict) -> int:
        seq = int(f.get("seq") or 0)
        if seq and any(int(e.get("seq") or 0) == seq for e in inst.events):
            return seq  # 幂等：同一 seq 只记录一次
        inst.events.append(f)
        inst.last_seq = max(inst.last_seq, seq)
        return inst.last_seq

    def _on_response(self, inst: Instance, f: dict) -> None:
        rid = str(f.get("id") or "")
        if not rid:
            return
        inst.responses[rid] = f
        holder = inst.pending.pop(rid, None)
        if holder is not None:
            holder["response"] = f
            holder["event"].set()
        # 订阅类响应用来刷新订阅视图
        if rid == "sub-init" or rid.startswith("sub-"):
            result = f.get("result")
            if isinstance(result, dict):
                inst.subscriptions = {
                    "topics": result.get("topics") or [],
                    "sessions": result.get("sessions") or [],
                    "assistantStreams": result.get("assistantStreams") or [],
                }

    # ── 下行：服务器 → 插件 ──────────────────────────────────────

    def _queue_locked(self, inst: Instance, f: dict) -> None:
        inst.inbox.append(f)
        if "seq" in f:
            inst.cursor = max(inst.cursor, int(f.get("seq") or 0))

    def queue(self, instance_id: str, f: dict) -> None:
        with self.cond:
            inst = self.instances.get(instance_id)
            if inst is None:
                raise UnknownInstance(instance_id)
            self._queue_locked(inst, f)
            self.cond.notify_all()

    def take_inbox(self, instance_id: str, wait_ms: int = POLL_MAX_MS) -> list | None:
        """长轮询：取出待发帧；无帧则挂起至多 wait_ms。返回 None 表示实例未知。"""
        wait_ms = max(0, min(int(wait_ms), POLL_MAX_MS))
        deadline = time.monotonic() + wait_ms / 1000.0
        with self.cond:
            while True:
                inst = self.instances.get(instance_id)
                if inst is None:
                    return None
                inst.last_seen_at = time.time()
                if inst.inbox:
                    out = list(inst.inbox)
                    inst.inbox.clear()
                    return out
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self.cond.wait(remaining)

    def request(self, instance_id: str, method: str, params: dict | None = None,
                timeout_ms: int = 30000) -> dict:
        """下发一个 request 并等待对应 response。"""
        rid = uuid.uuid4().hex
        holder = {"event": threading.Event(), "response": None}
        with self.cond:
            inst = self.instances.get(instance_id)
            if inst is None:
                raise UnknownInstance(instance_id)
            inst.pending[rid] = holder
            self._queue_locked(inst, frame("request", id=rid, method=method,
                                           params=params or {}))
            self.cond.notify_all()
        if not holder["event"].wait(timeout_ms / 1000.0):
            with self.cond:
                inst = self.instances.get(instance_id)
                if inst is not None:
                    inst.pending.pop(rid, None)
            raise RequestTimeout(method)
        return holder["response"]

    def subscribe(self, instance_id: str, topics=None, sessions=None,
                  assistant_stream: bool = False, snapshot: bool = True) -> str:
        rid = f"sub-{uuid.uuid4().hex[:8]}"
        payload = frame("subscribe", id=rid, snapshot=snapshot)
        if topics is not None:
            payload["topics"] = list(topics)
        if sessions is not None:
            payload["sessions"] = list(sessions)
        if assistant_stream:
            payload["assistantStream"] = True
        self.queue(instance_id, payload)
        return rid

    # ── 查询 ────────────────────────────────────────────────────

    def snapshot(self) -> list[dict]:
        with self.lock:
            now = time.time()
            return [
                {
                    "instanceId": i.instance_id,
                    "label": i.label,
                    "username": i.username,
                    "keyFingerprint": i.key_fingerprint,
                    "transport": i.transport,
                    "tls": i.tls,
                    "connectedAt": int(i.connected_at * 1000),
                    "lastSeenAt": int(i.last_seen_at * 1000),
                    "disconnectedAt": (int(i.disconnected_at * 1000)
                                       if i.disconnected_at else None),
                    "online": self._online(i, now),
                    "protocol": PROTOCOL_VERSION,
                    "capabilities": i.capabilities,
                    "subscriptions": i.subscriptions,
                    "eventCount": len(i.events),
                    "lastEventKind": (i.events[-1].get("kind") if i.events else None),
                    "lastSeq": i.last_seq,
                    "ageSeconds": round(now - i.last_seen_at, 1),
                }
                for i in self.instances.values()
            ]

    def instance_for_user(self, username: str) -> str | None:
        """该用户名下当前在线的实例 id。

        用于「用户只能访问自己的实例」的校验（spec §8 约束 6）。
        没有任何实例命中时返回 None，调用方应据此拒绝请求（fail closed）。
        """
        if not username:
            return None
        now = time.time()
        with self.lock:
            for inst in self.instances.values():
                if inst.username == username and self._online(inst, now):
                    return inst.instance_id
        return None

    def last_seq(self, instance_id: str) -> int | None:
        """该实例当前的最大事件序号；实例未知返回 None。

        用于"下发提示词前先记下水位"，这样随后只转发本轮产生的事件。
        """
        with self.lock:
            inst = self.instances.get(instance_id)
            return None if inst is None else inst.last_seq

    def events_since(self, instance_id: str, since: int = 0, limit: int = 200):
        with self.lock:
            inst = self.instances.get(instance_id)
            if inst is None:
                return None
            frames = [e for e in inst.events if int(e.get("seq") or 0) > since]
            return frames[-limit:], inst.last_seq

    def wait_events(self, instance_id: str, since: int = 0,
                    wait_ms: int = POLL_MAX_MS):
        """阻塞等待 ``seq > since`` 的新事件。

        返回 ``(frames, last_seq, timed_out)``；实例未知时返回 ``None``。
        与 ``events_since`` 的区别是会挂起，供 SSE 转发层按序消费。
        """
        deadline = time.monotonic() + max(0, wait_ms) / 1000.0
        with self.cond:
            while True:
                inst = self.instances.get(instance_id)
                if inst is None:
                    return None
                frames = [e for e in inst.events if int(e.get("seq") or 0) > since]
                if frames:
                    return frames, inst.last_seq, False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return [], inst.last_seq, True
                self.cond.wait(remaining)
