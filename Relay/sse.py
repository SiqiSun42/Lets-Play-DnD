"""把 dsh2server 的事件翻译成现有前端认识的事件，并编码为 SSE。

前端契约（`UI/js/chat-view.js`）：

    thinking     { delta }
    content      { delta }
    new_bubble   -
    end_bubble   -
    done         { content, thinking, segmented, soft_locked? }
    error        { error }

**续传**：每条 SSE 都带 ``id: <seq>``，``seq`` 是 DSH 事件的日志序号。
调用方在断线后用该值作为 ``since_seq`` 重连，中转服务器会从事件环补齐缺口
（配合 ``RelayState.wait_events``）。
"""

from __future__ import annotations

import json
from typing import Iterator

# 前端事件类型
EV_THINKING = "thinking"
EV_CONTENT = "content"
EV_NEW_BUBBLE = "new_bubble"
EV_END_BUBBLE = "end_bubble"
EV_DONE = "done"
EV_ERROR = "error"

# 事件种类（dsh2server 规范 §8）
KIND_ASSISTANT_STREAM = "session/assistant-stream"
KIND_STATUS = "session/status"


def frame_to_frontend(ev: dict) -> list[dict]:
    """把一个中转事件翻译成 0..n 个前端事件。"""
    kind = ev.get("kind")
    data = ev.get("data") or {}

    if kind == KIND_ASSISTANT_STREAM:
        frame = data.get("frame") or {}
        ftype = frame.get("type")
        if ftype == "start":
            return [{"type": EV_NEW_BUBBLE}]
        if ftype == "end":
            return [{"type": EV_END_BUBBLE}]
        if ftype == "chunk":
            chunk = frame.get("chunk") or {}
            ctype = chunk.get("type")
            if ctype == "reasoning-delta" and chunk.get("text"):
                return [{"type": EV_THINKING, "delta": chunk["text"]}]
            if ctype == "text-delta" and chunk.get("text"):
                return [{"type": EV_CONTENT, "delta": chunk["text"]}]
            # block-start / block-end / tool-call-delta / usage / finish
            # 暂不向前端暴露，留待需要工具卡片时再补。
        return []

    return []


def encode_sse(payload: dict, seq: int | None = None) -> str:
    """编码一条 SSE 消息。带 ``id:`` 以便断线续传。"""
    lines = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append("data: " + json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


def is_turn_finished(ev: dict, session_id: str) -> bool:
    """该事件是否表示这一轮已经结束（会话回到 idle）。"""
    if ev.get("kind") != KIND_STATUS:
        return False
    data = ev.get("data") or {}
    if data.get("sessionId") != session_id:
        return False
    return data.get("status") == "idle" or data.get("running") is False


def iter_frontend(state, instance_id: str, session_id: str,
                  since_seq: int = 0,
                  idle_timeout_ms: int = 25000,
                  overall_timeout_s: float = 600.0) -> Iterator[str]:
    """消费某个会话的事件流，产出可直接写进 SSE 响应体的字符串。

    ``since_seq`` 用于续传：从该序号之后重放，再继续跟随。

    终止条件：收到该会话的 ``session/status = idle``、实例消失、或整体超时。
    """
    import time

    deadline = time.monotonic() + overall_timeout_s
    seq = int(since_seq or 0)
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    settled = False
    seen_any = False

    while time.monotonic() < deadline:
        got = state.wait_events(instance_id, since=seq, wait_ms=idle_timeout_ms)
        if got is None:
            yield encode_sse({"type": EV_ERROR, "error": "instance disconnected"})
            return
        frames, last_seq, timed_out = got
        if not frames:
            if timed_out and seen_any and not settled:
                # 这一轮已经开始过，却长时间毫无动静：收尾，不无限挂着。
                break
            # 尚未等到任何本会话事件（例如提示词刚下发）：继续等，由整体超时兜底。
            continue

        for ev in frames:
            seq = max(seq, int(ev.get("seq") or seq))

            # 只处理本会话的事件，避免把同一实例上其他会话的流混进来。
            if (ev.get("data") or {}).get("sessionId") != session_id:
                continue
            seen_any = True

            for payload in frame_to_frontend(ev):
                if payload["type"] == EV_THINKING:
                    thinking_parts.append(payload["delta"])
                elif payload["type"] == EV_CONTENT:
                    content_parts.append(payload["delta"])
                yield encode_sse(payload, seq=seq)

            if is_turn_finished(ev, session_id):
                yield encode_sse({
                    "type": EV_DONE,
                    "content": "".join(content_parts),
                    "thinking": "".join(thinking_parts),
                    "segmented": True,
                }, seq=seq)
                settled = True
                return

    if not settled:
        # 未能观察到 idle：仍然把已累积的内容交付，避免前端空等。
        yield encode_sse({
            "type": EV_DONE,
            "content": "".join(content_parts),
            "thinking": "".join(thinking_parts),
            "segmented": True,
        }, seq=seq)
