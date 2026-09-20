"""dsh2server 协议 v1 的 Flask Blueprint。

核心协议：``/events``（上行）、``/inbox``（下行长轮询）、``/ws``（明示不支持）。
管理接口：``/keys``、``/instances``、``/instances/<id>/{events,request,subscribe}``。

约束：状态在内存中 → **必须单进程**，且 Flask 需 ``threaded=True``（长轮询会占住 worker）。
"""

from __future__ import annotations

import hmac
import ipaddress
from functools import wraps

from flask import Blueprint, jsonify, request

from .protocol import (
    POLL_MAX_MS,
    PROTOCOL_VERSION,
    frame,
    fingerprint,
)
from .state import RequestTimeout, UnknownInstance

# 上游把 key 放在这些位置；规范 §2.2 给出优先级
# Authorization: Bearer → ?key= → 请求体 key → 批内首个 hello 帧的 auth.key


def _bearer(req) -> str | None:
    header = req.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _extract_key(req, hello_frame, body) -> str | None:
    key = _bearer(req)
    if key:
        return key
    key = req.args.get("key")
    if key:
        return key
    if isinstance(body, dict) and body.get("key"):
        return str(body["key"])
    if isinstance(hello_frame, dict):
        auth = hello_frame.get("auth")
        if isinstance(auth, dict) and auth.get("key"):
            return str(auth["key"])
    return None


def _is_loopback(req) -> bool:
    addr = req.remote_addr or ""
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def create_blueprint(state, base_path: str = "/dsh-api",
                     admin_key: str | None = None,
                     poll_max_ms: int = POLL_MAX_MS) -> Blueprint:
    bp = Blueprint("dsh_relay", __name__, url_prefix=base_path)

    def require_admin(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if admin_key:
                provided = request.headers.get("x-admin-key") or request.args.get("adminKey") or ""
                if not hmac.compare_digest(admin_key, provided):
                    return jsonify(error={"code": "unauthorized",
                                          "message": "management routes need x-admin-key"}), 401
            elif not _is_loopback(request):
                return jsonify(error={"code": "forbidden",
                                      "message": "management routes are loopback-only"}), 403
            return fn(*a, **kw)
        return wrapper

    # ── 协议信息 ────────────────────────────────────────────────
    @bp.get("/")
    def info():
        return jsonify(
            name="dsh2server relay (Flask)",
            protocol=PROTOCOL_VERSION,
            basePath=base_path,
            carriers={"http-long-poll": True, "websocket": False},
            endpoints={
                "events": f"{base_path}/events",
                "inbox": f"{base_path}/inbox",
                "instances": f"{base_path}/instances",
                "keys": f"{base_path}/keys",
            },
            pollMaxMs=poll_max_ms,
            keys=len(state.keys),
            instances=len(state.snapshot()),
        )

    # ── 上行：插件 → 服务器 ─────────────────────────────────────
    @bp.post("/events")
    def events():
        body = request.get_json(silent=True) or {}
        frames = body.get("frames") if isinstance(body.get("frames"), list) else []
        hello = next((f for f in frames
                      if isinstance(f, dict) and f.get("type") == "hello"), None)

        key = _extract_key(request, hello, body)
        entry = state.keys.authorize(key or "")
        if entry is None:
            return jsonify(error={"code": "unauthorized",
                                  "message": "unknown instance key"}), 401

        instance_id = str(
            body.get("instanceId")
            or (hello or {}).get("instanceId")
            or entry.get("instanceId")
            or ""
        )
        if not instance_id:
            return jsonify(error={"code": "bad_request",
                                  "message": "missing instanceId"}), 400

        tls = request.is_secure
        accepted = state.ingest(instance_id, entry, frames, transport="http", tls=tls)
        return jsonify(accepted=accepted)

    # ── 下行：插件 ← 服务器（长轮询）────────────────────────────
    @bp.get("/inbox")
    def inbox():
        key = _extract_key(request, None, None)
        entry = state.keys.authorize(key or "")
        if entry is None:
            return jsonify(error={"code": "unauthorized",
                                  "message": "unknown instance key"}), 401
        instance_id = str(request.args.get("instanceId") or entry.get("instanceId") or "")
        if not instance_id:
            return jsonify(error={"code": "bad_request",
                                  "message": "missing instanceId"}), 400
        wait_ms = request.args.get("waitMs", type=int) or poll_max_ms
        out = state.take_inbox(instance_id, wait_ms)
        if out is None:
            return jsonify(error={"code": "not_found",
                                  "message": "unknown instance; send hello first"}), 404
        with state.lock:
            cursor = state.instances[instance_id].cursor
        return jsonify(frames=out, cursor=cursor, waitMs=poll_max_ms)

    # ── WebSocket：明示不支持 ───────────────────────────────────
    @bp.get("/ws")
    def ws_unsupported():
        return jsonify(error={
            "code": "websocket_unsupported",
            "message": ("this relay serves HTTP long-polling only; "
                        "the plugin falls back automatically under transport=auto"),
        }), 426

    # ── 管理：key 白名单 ────────────────────────────────────────
    @bp.get("/keys")
    @require_admin
    def keys_list():
        return jsonify(keys=state.keys.list_public())

    @bp.post("/keys")
    @require_admin
    def keys_add():
        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "")
        if not key:
            return jsonify(error={"code": "invalid_params", "message": "key is required"}), 400
        entry = state.keys.add(key, label=body.get("label"),
                               instance_id=body.get("instanceId"))
        return jsonify(added={"fingerprint": fingerprint(key),
                              "label": entry.get("label")})

    @bp.post("/keys/remove")
    @require_admin
    def keys_remove():
        body = request.get_json(silent=True) or {}
        key = str(body.get("key") or "")
        if not key:
            return jsonify(error={"code": "invalid_params", "message": "key is required"}), 400
        return jsonify(removed=state.keys.remove(key))

    # ── 管理：实例 ──────────────────────────────────────────────
    @bp.get("/instances")
    @require_admin
    def instances():
        return jsonify(instances=state.snapshot())

    @bp.get("/instances/<instance_id>/events")
    @require_admin
    def instance_events(instance_id):
        since = request.args.get("since", default=0, type=int) or 0
        limit = min(request.args.get("limit", default=200, type=int) or 200, 1000)
        got = state.events_since(instance_id, since=since, limit=limit)
        if got is None:
            return jsonify(error={"code": "not_found",
                                  "message": f'no connected instance "{instance_id}"'}), 404
        frames, last_seq = got
        return jsonify(events=frames, lastSeq=last_seq)

    @bp.post("/instances/<instance_id>/request")
    @require_admin
    def instance_request(instance_id):
        body = request.get_json(silent=True) or {}
        method = body.get("method")
        if not isinstance(method, str) or not method:
            return jsonify(error={"code": "invalid_params", "message": "method is required"}), 400
        try:
            resp = state.request(instance_id, method,
                                 body.get("params") or {},
                                 timeout_ms=int(body.get("timeoutMs") or 30000))
        except UnknownInstance:
            return jsonify(error={"code": "not_found",
                                  "message": f'no connected instance "{instance_id}"'}), 404
        except RequestTimeout:
            return jsonify(ok=False, error={"code": "timeout",
                                            "message": f"{method} timed out"}), 504
        return jsonify(resp)

    @bp.post("/instances/<instance_id>/subscribe")
    @require_admin
    def instance_subscribe(instance_id):
        body = request.get_json(silent=True) or {}
        try:
            rid = state.subscribe(
                instance_id,
                topics=body.get("topics"),
                sessions=body.get("sessions"),
                assistant_stream=bool(body.get("assistantStream")),
                snapshot=body.get("snapshot") is not False,
            )
        except UnknownInstance:
            return jsonify(error={"code": "not_found",
                                  "message": f'no connected instance "{instance_id}"'}), 404
        return jsonify(queued=True, id=rid), 202

    return bp
