from .battle_zh import (
    start_battle_turn,
    prepare_actor_action_branch,
    run_allies_first_check,
    run_allies_second_check,
    run_allies_action,
    run_enemies_action,
    run_enemies_check,
    run_battle_update,
    load_battle_status,
    save_battle_status,
    advance_battle_turn,
    sync_battle_runtime,
)
from .battle_end_zh import run_battle_end, is_save_soft_locked

BATTLE_LOOP_MAX_STEPS = 64


def _append_event(events: list, kind: str, text: str | None) -> None:
    content = (text or "").strip()
    if not content:
        return
    events.append({"kind": kind, "content": content})


def _update_turn(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> dict:
    return run_battle_update(
        username,
        save_id,
        user_text=user_text,
        pre_content=pre_content,
        dm_content=dm_content,
    )


def _after_update(
    username: str,
    save_id: str,
    events: list,
    update_result: dict,
) -> dict | None:
    if update_result.get("is_battle_ended") is not True:
        return None
    end_result = run_battle_end(
        username,
        save_id,
        user_text=update_result.get("user_text"),
        pre_content=update_result.get("pre_content"),
        dm_content=update_result.get("dm_content"),
    )
    for item in end_result.get("events") or []:
        _append_event(events, item.get("kind") or "dm", item.get("content"))
    if end_result.get("status") == "continue_battle":
        return None
    return {
        "status": end_result.get("status"),
        "ending": end_result.get("ending"),
        "message": end_result.get("message"),
        "prompt": end_result.get("prompt"),
        "content": end_result.get("content"),
        "dice_text": end_result.get("dice_text"),
        "events": events,
        "update_result": update_result,
        "turn_result": None,
    }


def _run_shared_resolve(
    username: str,
    save_id: str,
    first_like: dict,
    events: list,
) -> dict | None:
    second = run_allies_second_check(username, save_id, first_like)
    if second.get("outcome") == "error":
        return {
            "status": "error",
            "message": second.get("message") or "二次检定失败。",
            "prompt": None,
            "events": events,
            "turn_result": first_like.get("turn_result"),
        }

    if second.get("outcome") == "content_only":
        _append_event(events, "dm", second.get("content"))
        update_result = _update_turn(
            username,
            save_id,
            user_text=first_like.get("user_text"),
            pre_content=(first_like.get("turn_result") or {}).get("content"),
            dm_content=second.get("content"),
        )
        stop = _after_update(username, save_id, events, update_result)
        if stop:
            return stop
        if not update_result.get("is_battle_forward"):
            return {
                "status": "waiting_for_input",
                "message": None,
                "prompt": None,
                "events": events,
                "turn_result": first_like.get("turn_result"),
                "update_result": update_result,
            }
        return None

    if second.get("action_valid") is False:
        _append_event(events, "dm", second.get("instruction"))
        update_result = _update_turn(
            username,
            save_id,
            user_text=first_like.get("user_text"),
            pre_content=(first_like.get("turn_result") or {}).get("content"),
            dm_content=second.get("instruction"),
        )
        stop = _after_update(username, save_id, events, update_result)
        if stop:
            return stop
        if not update_result.get("is_battle_forward"):
            return {
                "status": "waiting_for_input",
                "message": None,
                "prompt": None,
                "events": events,
                "turn_result": first_like.get("turn_result"),
                "update_result": update_result,
            }
        return None

    action = run_allies_action(username, save_id, second)
    if action.get("outcome") == "error":
        return {
            "status": "error",
            "message": action.get("message") or "动作结算失败。",
            "prompt": None,
            "events": events,
            "turn_result": first_like.get("turn_result"),
        }

    _append_event(events, "dm", action.get("content"))
    update_result = _update_turn(
        username,
        save_id,
        user_text=first_like.get("user_text"),
        pre_content=(first_like.get("turn_result") or {}).get("content"),
        dm_content=action.get("content"),
    )
    stop = _after_update(username, save_id, events, update_result)
    if stop:
        return stop
    if not update_result.get("is_battle_forward"):
        return {
            "status": "waiting_for_input",
            "message": None,
            "prompt": None,
            "events": events,
            "turn_result": first_like.get("turn_result"),
            "update_result": update_result,
        }
    return None


def _run_allies_with_input(
    username: str,
    save_id: str,
    turn_result: dict,
    user_text: str,
    events: list,
) -> dict | None:
    first = run_allies_first_check(username, save_id, turn_result, user_text)
    if first.get("outcome") == "error":
        return {
            "status": "error",
            "message": first.get("message") or "动作初检失败。",
            "prompt": None,
            "events": events,
            "turn_result": turn_result,
        }

    if first.get("outcome") == "content_only" or first.get("action_valid") is False:
        _append_event(events, "dm", first.get("content") or first.get("note"))
        update_result = _update_turn(
            username,
            save_id,
            user_text=user_text,
            pre_content=turn_result.get("content"),
            dm_content=first.get("content") or first.get("note"),
        )
        stop = _after_update(username, save_id, events, update_result)
        if stop:
            return stop
        if not update_result.get("is_battle_forward"):
            return {
                "status": "waiting_for_input",
                "message": None,
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
                "update_result": update_result,
            }
        return None

    return _run_shared_resolve(username, save_id, first, events)


def _run_enemy_actor(
    username: str,
    save_id: str,
    turn_result: dict,
    events: list,
) -> dict | None:
    generated = run_enemies_action(username, save_id, turn_result)
    if generated.get("outcome") != "generated":
        return {
            "status": "error",
            "message": generated.get("message") or "敌人候选动作生成失败。",
            "prompt": None,
            "events": events,
            "turn_result": turn_result,
        }

    checked = run_enemies_check(username, save_id, generated)
    if checked.get("outcome") == "error":
        return {
            "status": "error",
            "message": checked.get("message") or "敌人动作选择失败。",
            "prompt": None,
            "events": events,
            "turn_result": turn_result,
        }

    if checked.get("outcome") == "content_only" or not checked.get("chosen_action"):
        _append_event(events, "dm", checked.get("content"))
        update_result = _update_turn(
            username,
            save_id,
            pre_content=turn_result.get("content"),
            dm_content=checked.get("content"),
        )
        stop = _after_update(username, save_id, events, update_result)
        if stop:
            return stop
        if not update_result.get("is_battle_forward"):
            return {
                "status": "error",
                "message": "敌人未能选定有效动作。",
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
                "update_result": update_result,
            }
        return None

    return _run_shared_resolve(username, save_id, checked, events)


def run_battle_loop(
    username: str,
    save_id: str,
    user_text: str | None = None,
) -> dict:
    events: list = []
    pending_user = (user_text or "").strip() or None

    if is_save_soft_locked(username, save_id):
        return {
            "status": "soft_locked",
            "message": None,
            "prompt": None,
            "events": events,
            "turn_result": None,
        }

    sync_battle_runtime(username, save_id)

    battle_status = load_battle_status(username, save_id) or {}
    if battle_status.get("ending_phase") == "character_check":
        end_result = run_battle_end(
            username,
            save_id,
            user_text=pending_user,
        )
        for item in end_result.get("events") or []:
            _append_event(events, item.get("kind") or "dm", item.get("content"))
        return {
            "status": end_result.get("status"),
            "ending": end_result.get("ending"),
            "message": end_result.get("message"),
            "prompt": end_result.get("prompt"),
            "content": end_result.get("content"),
            "dice_text": end_result.get("dice_text"),
            "events": events,
            "turn_result": None,
        }

    for _ in range(BATTLE_LOOP_MAX_STEPS):
        turn_result = start_battle_turn(username, save_id)
        outcome = turn_result.get("outcome")

        if outcome == "idle":
            return {
                "status": "idle",
                "message": None,
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
            }

        if outcome == "error":
            return {
                "status": "error",
                "message": turn_result.get("message") or "战斗回合启动失败。",
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
            }

        if outcome == "pre_error":
            return {
                "status": "error",
                "message": turn_result.get("message") or "战斗前置结算失败。",
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
            }

        if outcome == "skipped":
            _append_event(events, "system", turn_result.get("message"))
            continue

        branch_info = prepare_actor_action_branch(turn_result)
        branch = branch_info.get("branch")

        if branch == "none":
            return {
                "status": "error",
                "message": "当前回合无法确定动作分支。",
                "prompt": None,
                "events": events,
                "turn_result": turn_result,
            }

        if branch == "write_only":
            _append_event(events, "dm", turn_result.get("content"))
            update_result = _update_turn(
                username,
                save_id,
                pre_content=turn_result.get("content"),
                dm_content=turn_result.get("content"),
            )
            stop = _after_update(username, save_id, events, update_result)
            if stop:
                return stop
            if not update_result.get("is_battle_forward"):
                battle_status = load_battle_status(username, save_id)
                if battle_status:
                    advance_battle_turn(battle_status)
                    save_battle_status(username, save_id, battle_status)
            continue

        if branch == "allies":
            if not pending_user:
                return {
                    "status": "waiting_for_input",
                    "message": None,
                    "prompt": branch_info.get("prompt"),
                    "events": events,
                    "turn_result": turn_result,
                }
            text = pending_user
            pending_user = None
            stop = _run_allies_with_input(
                username, save_id, turn_result, text, events
            )
            if stop:
                if stop.get("status") == "waiting_for_input" and not stop.get("prompt"):
                    stop["prompt"] = branch_info.get("prompt")
                return stop
            continue

        if branch == "enemy":
            stop = _run_enemy_actor(username, save_id, turn_result, events)
            if stop:
                return stop
            continue

        return {
            "status": "error",
            "message": f"未知战斗分支：{branch}",
            "prompt": None,
            "events": events,
            "turn_result": turn_result,
        }

    return {
        "status": "error",
        "message": "战斗循环步数超过上限。",
        "prompt": None,
        "events": events,
        "turn_result": None,
    }
