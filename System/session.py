import json
from pathlib import Path

from System.api_client import configure_client, clear_client

ROOT = Path(__file__).resolve().parent.parent
_sessions = {}

CONSULT_ID = "consult"

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

def stop(username: str):
    if username in _sessions:
        del _sessions[username]
    clear_client()

def start(username: str, save_id: str, *, api_key: str, provider: str):
    stop(username)

    item = find_save_meta(username, save_id)
    language = item.get("in_game_language") or "zh-CN"
    is_consult = save_id == CONSULT_ID

    configure_client(api_key=api_key, provider=provider)

    _sessions[username] = {
        "username": username,
        "save_id": save_id,
        "language": language,
        "is_consult": is_consult,
    }
    return _sessions[username]