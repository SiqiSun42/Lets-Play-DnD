"""
1.首先根据玩家输入和上下文，大致判断这回合是什么“类别”（元对话；属性检定；游戏动作；角色互动；环境探索）然后根据类别进入不同的分支流程。这一步也可以粗略加一个判断环境是否危险。
2.有些类别需要额外环节获取信息，比如查询规则书或者投掷骰子（属性检定，游戏动作，元对话；如果是自由探索/交互通常不用）。记忆RAG等完成后也在这一步加入。
3.根据上下文、提示词和返回信息，生成这一回合的推进文本。如果有润色文本也在这一回合添加。
4.根据结果更新笔记（时间，状态，位置，诸如此类……）
5.（暂时不做）在危险环境下判断是否进入战斗分支
"""

import json

from System import call_model, history_for_model
from Dice import roll_dice
from Prompts import CLASSIFY_ZH_PROMPT, PREPARE_ZH_PROMPT
from Tools import classify_tool, normalize_classify_category, dice_tool_zh, rag_tools_zh

CLASSIFY_INPUT_ERROR = "抱歉，系统未成功接收您上回合的输入，请重新输入。"
CLASSIFY_MAX_ATTEMPTS = 3

prepare_tools = dice_tool_zh + rag_tools_zh


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
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            if func_name == "classify_turn":
                category = normalize_classify_category(args.get("category"))
                return category
            else:
                return None

def _build_prepare_messages(history_msgs: list, text: str, previous_text: str) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": PREPARE_ZH_PROMPT})
    messages.append({"role": "user", "content": text})
    messages.extend(previous_text)
    return messages


def prepare(history_msgs: list, user_text: str, previous_text: list) -> list:
    messages = _build_prepare_messages(history_msgs, user_text, previous_text)
    result = call_model(
        messages,
        tools=prepare_tools,
    )
    msg = result["message"]

    if not msg.tool_calls:
        return previous_text

    dice_lines = []
    rag_parts = []
    for tool_call in msg.tool_calls:
        from RAG import search_rules
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "roll_dice":
            names = args.get("names", "")
            dice_type = args.get("dice_type", "")
            num = args.get("nums", 1)
            sides = args.get("sides", 20)
            rolls = roll_dice(num, sides)
            dice_lines.append(
                f"骰子使用者：{names}，类型：{dice_type}，数量和面数：{num}d{sides}，结果：{rolls}"
            )
        elif func_name == "search_rules":
            query = args.get("query")
            context_label = args.get("context_label", "")
            rag_text = search_rules(query, language="zh-CN")
            rag_parts.append(f"[{context_label}]\n{rag_text}")

    if rag_parts:
        previous_text.append({"role": "system", "content": "以下是从规则书中检索到的相关内容：\n\n" + "\n\n---\n\n".join(rag_parts)})
    if dice_lines:
        previous_text.append({"role": "system", "content": "这是系统提供的本回合骰子值：\n" + "\n".join(dice_lines)})

    return previous_text

def run_stream_game_zh(username: str, save_id: str, text: str):
    history = history_for_model(username, save_id)
    history_msgs = history[-20:]

    user_text = text.strip()
    previous_text = []

    category = None
    for _ in range(CLASSIFY_MAX_ATTEMPTS):
        category = classify(history_msgs, user_text)
        if category:
            previous_text.append({"role": "system", "content": f"本回合对话的类别是：{category}"})
            break

    if not category:
        yield {"type": "error", "content": CLASSIFY_INPUT_ERROR}
        return

    previous_text = prepare(history_msgs, user_text, previous_text)

    yield {"type": "classified", "category": category}