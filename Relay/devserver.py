"""独立运行中转服务器，用于本地验收。

生产环境不跑这个入口：应由 ``server.py`` 直接 ``register_blueprint``，
以保证**单进程**（实例状态在内存中）。

    python -m Relay.devserver --port 8788 --keys /tmp/relay-keys.json
"""

from __future__ import annotations

import argparse

from flask import Flask

from .blueprint import create_blueprint
from .state import KeyStore, RelayState

DEFAULT_BASE_PATH = "/dsh-api"


def create_app(keys_path: str | None = None,
               admin_key: str | None = None,
               base_path: str = DEFAULT_BASE_PATH) -> Flask:
    app = Flask(__name__)
    state = RelayState(KeyStore(keys_path))
    app.register_blueprint(
        create_blueprint(state, base_path=base_path, admin_key=admin_key)
    )
    # 供同进程的其他模块（如 SSE 翻译层）取用
    app.extensions["dsh_relay_state"] = state
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description="dsh2server relay (dev)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--keys", default=None, help="key 白名单 JSON 路径")
    ap.add_argument("--admin-key", default=None)
    ap.add_argument("--base-path", default=DEFAULT_BASE_PATH)
    args = ap.parse_args()

    app = create_app(keys_path=args.keys, admin_key=args.admin_key,
                     base_path=args.base_path)
    state = app.extensions["dsh_relay_state"]
    print("dsh2server relay (Flask)")
    print(f"  base       : http://{args.host}:{args.port}{args.base_path}")
    print(f"  events     : POST {args.base_path}/events")
    print(f"  inbox      : GET  {args.base_path}/inbox")
    print(f"  keys file  : {args.keys or '(memory only)'}")
    print(f"  registered : {len(state.keys)}")
    # threaded=True 是必需的：长轮询会占住 worker
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
