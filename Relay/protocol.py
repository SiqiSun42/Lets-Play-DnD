"""dsh2server 协议 v1 的服务端常量。

规范：见 dsh2server 插件的 docs/API.md。
"""

PROTOCOL_VERSION = 1

# ── 插件 → 服务器 ──────────────────────────────────────────────
F_HELLO = "hello"
F_EVENT = "event"
F_RESPONSE = "response"
F_PING = "ping"
F_ACK = "ack"
F_BYE = "bye"
F_LOG = "log"

# ── 服务器 → 插件 ──────────────────────────────────────────────
F_HELLO_ACK = "hello.ack"
F_REQUEST = "request"
F_SUBSCRIBE = "subscribe"
F_UNSUBSCRIBE = "unsubscribe"
F_PONG = "pong"
F_ERROR = "error"

# 订阅主题（规范 §7）
TOPICS = ("instance", "sessions", "session", "jobs", "approvals", "goals")

# 默认自动订阅的主题
DEFAULT_TOPICS = ("instance", "sessions", "jobs", "approvals")

# 实例侧限制
EVENT_RING_LIMIT = 2000      # 每实例保留的事件条数（规范推荐值）
INBOX_LIMIT = 500            # 每实例待发队列上限
POLL_MAX_MS = 25000          # 长轮询单次挂起上限
HEARTBEAT_MS = 30000

# 过期判定（规范 §12：把 lastSeenAt 超过一段时间未更新的实例视为离线）
# 插件的 heartbeatMs 默认 30s、自身超时 90s，服务器取同一量级。
STALE_AFTER_SECONDS = 90.0
# 离线超过这个时长后整条记录被回收，避免僵尸实例无限累积。
RETENTION_SECONDS = 3600.0


def frame(frame_type, **fields):
    """构造一个协议帧。"""
    return {"v": PROTOCOL_VERSION, "type": frame_type, **fields}


def error_frame(code, message, fatal=False, details=None):
    payload = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    if fatal:
        payload["fatal"] = True
    return frame(F_ERROR, **payload)


def fingerprint(key):
    """密钥指纹：仅用于展示，绝不回显完整密钥。"""
    if not key:
        return None
    if len(key) <= 14:
        return key
    return f"{key[:10]}\u2026{key[-4:]}"
