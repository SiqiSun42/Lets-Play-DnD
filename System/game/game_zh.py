"""
1.首先根据玩家输入和上下文，大致判断这回合是什么“类别”（元对话；属性检定；游戏动作；角色互动；环境探索）然后根据类别进入不同的分支流程。
2.有些类别需要额外环节获取信息，比如查询规则书或者投掷骰子（属性检定，游戏动作，元对话；如果是自由探索/交互通常不用）
3.根据上下文、提示词和返回信息，生成这一回合的推进文本
4.根据结果更新笔记（时间，状态，位置，诸如此类……）
5.（暂时不做）判断是否进入战斗分支
"""

import json

from System import call_model, history_for_model
from Prompts import CLASSIFY_ZH_PROMPT
from Tools import classify_tool, normalize_classify_category

CLASSIFY_INPUT_ERROR = "抱歉，系统未成功接收您上回合的输入，请重新输入。"
CLASSIFY_MAX_ATTEMPTS = 3


def _build_classify_messages(history_msgs: list, text: str) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": CLASSIFY_ZH_PROMPT})
    messages.append({"role": "user", "content": text})
    return messages


def classify(history_msgs: list, user_text: str) -> str | None:
    messages = _build_classify_messages(history_msgs, user_text)
    result = call_model(
        messages,
        tools=classify_tool,
    )
    msg = result["message"]
    
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            if tool_call.function.name == "classify_turn":
                args = json.loads(tool_call.function.arguments)
                category = normalize_classify_category(args.get("category"))
                return category
    else:
        return None

def run_stream_game_zh(username: str, save_id: str, text: str):
    history = history_for_model(username, save_id)
    history_msgs = history[-20:]

    user_text = text.strip()

    category = None
    for _ in range(CLASSIFY_MAX_ATTEMPTS):
        category = classify(history_msgs, user_text)
        if category:
            break

    if not category:
        yield {"type": "error", "content": CLASSIFY_INPUT_ERROR}
        return

    yield {"type": "classified", "category": category}