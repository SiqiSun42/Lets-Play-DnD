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
    """把一个中转事件翻译成 0..n 个前端事件。

    **刻意不产出 `new_bubble` / `end_bubble`。**

    DSH 的一个回合可能包含多个 step（模型 → 工具 → 模型），每个 step 都有自己的
    start/end。若按 step 发气泡边界，前端就会把一轮切成多个 DM 气泡——典型症状是
    「某步只有思考没有正文，于是出现一个只有思考的气泡 + 一个只有正文的气泡」。
    而落库的是**整条** assistant 消息，所以刷新后又变回正确的单气泡，两边不一致。

    前端的 `thinking` / `content` 分支各自会调用 `openBubbleForWrite()`，因此
    不需要边界事件来开气泡；整轮共用一个，由 `done` 收尾。思考与正文都按整轮
    累计，正好与落库后的呈现一致。

    **将来若要恢复边界**：`frame.type == "start"` → `EV_NEW_BUBBLE`、
    `"end"` → `EV_END_BUBBLE` 即可（前两个版本就是这么做的）。预期用途是
    battle 里 DM 一口气推进多个回合、需要拆成多个气泡的场景。届时要先想清楚
    "一个气泡"对应 DSH 的什么单位——是 step，还是别的边界。
    """
    kind = ev.get("kind")
    data = ev.get("data") or {}

    if kind == KIND_ASSISTANT_STREAM:
        frame = data.get("frame") or {}
        # start / end 是 step 边界，不发气泡事件。
        if frame.get("type") != "chunk":
            return []
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
    """编码一条 SSE 消息。

    ⚠️ **只发 ``data:`` 行，不发 SSE 标准的 ``id:`` 行。**

    前端解析器（`UI/js/chat-view.js`）按 ``part.trim().startsWith('data:')``
    判断整个块，块里一旦出现 ``id:`` 就会被**整条丢弃**——实测症状是
    「服务端执行成功并已落库、刷新能看到回复，但前端一个字都不渲染」。

    续传所需的序号改放进 JSON 载荷的 ``seq`` 字段：现有前端会忽略它，
    将来要续传时直接读即可，两边都不必改协议。
    """
    if seq is not None:
        payload = {**payload, "seq": int(seq)}
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


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
                  overall_timeout_s: float = 600.0,
                  on_done=None) -> Iterator[str]:
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
                done = {
                    "type": EV_DONE,
                    "content": "".join(content_parts),
                    "thinking": "".join(thinking_parts),
                    "segmented": True,
                }
                if on_done is not None:
                    on_done(done)
                yield encode_sse(done, seq=seq)
                settled = True
                return

    if not settled:
        # 未能观察到 idle：仍然把已累积的内容交付，避免前端空等。
        done = {
            "type": EV_DONE,
            "content": "".join(content_parts),
            "thinking": "".join(thinking_parts),
            "segmented": True,
        }
        if on_done is not None:
            on_done(done)
        yield encode_sse(done, seq=seq)
