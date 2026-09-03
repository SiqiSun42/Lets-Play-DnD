import copy
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import OpenAI

import System.api_client as api_client
from System.game.game_zh import classify, prepare

TEST_FUNC = "prepare"  # "classify", "prepare"
HISTORY_KEY = "history_3"
USER_TEXT = "是的，进行一次察觉检定。"
PREVIOUS_TEXT_KEY = "previous_2"

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
            "content": "是否要进行一次察觉检定？",
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

PREVIOUS_TEXTS = {
    "previous_0": [],
    "previous_1": [
        {"role": "system", "content": "本回合对话的类别是：元对话"},
    ],
    "previous_2": [
        {"role": "system", "content": "本回合对话的类别是：属性检定"},
    ],
    "previous_3": [
        {"role": "system", "content": "本回合对话的类别是：游戏动作"},
    ],
    "previous_4": [
        {"role": "system", "content": "本回合对话的类别是：元对话"},
        {
            "role": "system",
            "content": (
                "以下是从规则书中检索到的相关内容：\n\n"
                "[护甲等级]\n"
                "（此处为模拟 RAG 摘录，用于测试 prepare 已有规则上下文时的行为。）"
            ),
        },
    ],
    "previous_5": [
        {"role": "system", "content": "本回合对话的类别是：属性检定"},
        {
            "role": "system",
            "content": (
                "这是系统提供的本回合骰子值：\n"
                "骰子使用者：玩家，类型：感知（察觉）检定，数量和面数：1d20，结果：[14]"
            ),
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


def _get_history():
    if HISTORY_KEY not in HISTORIES:
        raise KeyError(f"unknown history: {HISTORY_KEY}")
    return HISTORIES[HISTORY_KEY]


def _get_previous_text():
    if PREVIOUS_TEXT_KEY not in PREVIOUS_TEXTS:
        raise KeyError(f"unknown previous_text: {PREVIOUS_TEXT_KEY}")
    return copy.deepcopy(PREVIOUS_TEXTS[PREVIOUS_TEXT_KEY])


def _print_previous_text(label: str, items: list):
    print(label)
    if not items:
        print("  (empty)")
        return
    for i, item in enumerate(items):
        print(f"  [{i}] role={item['role']}")
        print(f"      {item['content']}")


def run_classify():
    history = _get_history()
    result = classify(history, USER_TEXT)
    print(f"func: {TEST_FUNC}")
    print(f"history: {HISTORY_KEY}")
    print(f"input: {USER_TEXT!r}")
    print(f"model: {api_client.MODEL}")
    print(f"result: {result!r}")


def run_prepare():
    history = _get_history()
    previous_text = _get_previous_text()
    before_len = len(previous_text)

    result = prepare(history, USER_TEXT, previous_text)

    print(f"func: {TEST_FUNC}")
    print(f"history: {HISTORY_KEY}")
    print(f"previous_text: {PREVIOUS_TEXT_KEY}")
    print(f"input: {USER_TEXT!r}")
    print(f"model: {api_client.MODEL}")
    print(f"added: {len(result) - before_len} item(s)")
    print()
    _print_previous_text("previous_text (after prepare):", result)


RUNNERS = {
    "classify": run_classify,
    "prepare": run_prepare,
}


def main():
    _setup_test_client()

    if TEST_FUNC not in RUNNERS:
        raise SystemExit(f"unknown TEST_FUNC: {TEST_FUNC!r}, options: {list(RUNNERS)}")

    RUNNERS[TEST_FUNC]()


if __name__ == "__main__":
    main()
