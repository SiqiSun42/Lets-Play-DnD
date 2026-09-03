import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import OpenAI

import System.api_client as api_client
from System.game.game_zh import classify

TEST_FUNC = "classify"
HISTORY_KEY = "history_1"
USER_TEXT = "我攻击前面的哥布林"

HISTORIES = {
    "history_1": [],
    "history_2": [
        {
            "role": "assistant",
            "content": "你推开酒馆的木门，喧闹声和麦酒的气味扑面而来。酒保正擦着杯子看向你。",
        },
    ],
    "history_3": [
        {
            "role": "assistant",
            "content": "走廊尽头传来轻微的脚步声，你怀疑有人正在跟踪你们。",
        },
        {
            "role": "user",
            "content": "我想听听那边有没有异常。",
        },
        {
            "role": "assistant",
            "content": "可以，进行一次察觉检定。",
        },
    ],
    "history_4": [
        {
            "role": "assistant",
            "content": "盗贼从阴影里现身，匕首在烛光下闪着寒光。",
        },
        {
            "role": "user",
            "content": "我拔剑准备战斗。",
        },
        {
            "role": "assistant",
            "content": "他率先扑了上来，战斗开始了。",
        },
    ],
    "history_5": [
        {
            "role": "user",
            "content": "我的护甲等级是怎么算的？",
        },
        {
            "role": "assistant",
            "content": "你当前穿的是皮甲，敏捷调整值会加入护甲等级。",
        },
    ],
}


def _load_test_env():
    path = ROOT / ".env.local"
    if not path.is_file():
        raise SystemExit(f".env.local not found at {path}")
    load_dotenv(path)


def _setup_test_client():
    _load_test_env()

    api_key = (os.getenv("TEST_API_KEY") or "").strip()
    base_url = (os.getenv("TEST_MODEL_URL") or "").strip()
    model = (os.getenv("TEST_MODEL") or "").strip()
    thinking = os.getenv("TEST_THINKING_ENABLED", "true")
    effort = os.getenv("TEST_REASONING_EFFORT", "medium")

    if not api_key:
        raise SystemExit("TEST_API_KEY missing in .env.local")
    if not base_url:
        raise SystemExit("TEST_MODEL_URL missing in .env.local")
    if not model:
        raise SystemExit("TEST_MODEL missing in .env.local")

    api_client._client = OpenAI(api_key=api_key, base_url=base_url)
    api_client.MODEL = model
    api_client.THINKING_ENABLED = thinking.strip().lower() == "true"
    api_client.REASONING_EFFORT = effort.strip().strip('"')


def run_classify():
    if HISTORY_KEY not in HISTORIES:
        raise KeyError(f"unknown history: {HISTORY_KEY}")
    history = HISTORIES[HISTORY_KEY]
    result = classify(history, USER_TEXT)
    print(f"func: {TEST_FUNC}")
    print(f"history: {HISTORY_KEY}")
    print(f"input: {USER_TEXT!r}")
    print(f"model: {api_client.MODEL}")
    print(f"result: {result!r}")


RUNNERS = {
    "classify": run_classify,
}


def main():
    _setup_test_client()

    if TEST_FUNC not in RUNNERS:
        raise SystemExit(f"unknown TEST_FUNC: {TEST_FUNC!r}, options: {list(RUNNERS)}")

    RUNNERS[TEST_FUNC]()


if __name__ == "__main__":
    main()
