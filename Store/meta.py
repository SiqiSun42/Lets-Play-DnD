"""账号 meta.json 的读取（原件：`System/session.py`）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def account_dir(username: str) -> Path:
    return ROOT / "Account" / username

def meta_path(username: str) -> Path:
    return account_dir(username) / "meta.json"

def load_meta_list(username: str) -> list:
    path = meta_path(username)
    if not path.is_file():
        raise FileNotFoundError(f"meta missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("meta.json must be a list")
    return data

def find_save_meta(username: str, save_id: str) -> dict:
    for item in load_meta_list(username):
        if item.get("id") == save_id:
            return item
    raise KeyError(f"save not found: {save_id}")

