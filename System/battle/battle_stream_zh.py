from System.game import append_message


def emit_battle_bubbles(texts) -> list:
    events = []
    for raw in texts or []:
        text = (raw or "").strip()
        if not text:
            continue
        events.append({"type": "new_bubble"})
        events.append({"type": "content", "delta": text})
    return events


def iter_battle_result_sse(
    username: str,
    save_id: str,
    result: dict,
    *,
    prefix_content: str = "",
):
    status = result.get("status")
    already_persisted = status in (
        "waiting_for_character_check",
        "ended",
        "soft_locked",
    )

    pieces = []
    seen = set()

    def add_piece(text: str, *, persist: bool) -> None:
        content = (text or "").strip()
        if not content or content in seen:
            return
        seen.add(content)
        if persist:
            append_message(username, save_id, "assistant", content)
        pieces.append(content)

    add_piece(prefix_content, persist=False)
    for item in result.get("events") or []:
        add_piece(item.get("content"), persist=not already_persisted)
    prompt = (result.get("prompt") or "").strip()
    add_piece(prompt, persist=True)
    add_piece(result.get("content"), persist=not already_persisted)

    for text in pieces:
        yield {"type": "new_bubble"}
        yield {"type": "content", "delta": text}

    if status == "error":
        err = (result.get("message") or "战斗流程出错。").strip()
        yield {"type": "error", "error": err, "content": err}
        return

    done = {
        "type": "done",
        "segmented": True,
        "thinking": "",
        "battle_status": status,
    }
    if status == "soft_locked":
        done["soft_locked"] = True
    if prompt:
        done["prompt"] = prompt
    yield done


def iter_battle_continue_sse(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    start_parts=None,
):
    from .battle_zh import sync_battle_runtime
    from .battle_loop_zh import run_battle_loop

    for ev in emit_battle_bubbles(start_parts or []):
        yield ev

    sync_battle_runtime(username, save_id)
    result = run_battle_loop(
        username,
        save_id,
        user_text=user_text,
    )
    yield from iter_battle_result_sse(username, save_id, result)
