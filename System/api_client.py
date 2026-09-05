import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

_client = None
MODEL = None
THINKING_ENABLED = None
REASONING_EFFORT = None
def configure_client(*, api_key: str, provider: str):
    global _client, MODEL, THINKING_ENABLED, REASONING_EFFORT
    if not api_key:
        raise ValueError("api_key is empty")

    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    env_prefix = {
        "deepseek": "DEEPSEEK",
        "qwen": "QWEN",
        "openai": "OPENAI",
        "groq": "GROQ",
        "kimi": "KIMI",
    }.get(provider)
    if not env_prefix:
        raise ValueError(f"unsupported provider: {provider}")

    base_url = os.getenv(f"{env_prefix}_URL")
    model_name = os.getenv(f"{env_prefix}_MODEL")
    if not base_url or not model_name:
        raise ValueError(f"{env_prefix}_URL or {env_prefix}_MODEL missing in .env")
    _client = OpenAI(api_key=api_key, base_url=base_url)
    MODEL = model_name
    THINKING_ENABLED = os.getenv(f"{env_prefix}_THINKING_ENABLED", "true").lower() == "true"
    REASONING_EFFORT = os.getenv(f"{env_prefix}_REASONING_EFFORT", "medium").strip().strip('"')

def clear_client():
    global _client, MODEL, THINKING_ENABLED, REASONING_EFFORT
    _client = None
    MODEL = None
    THINKING_ENABLED = None
    REASONING_EFFORT = None


def _prepare_messages(messages: list, *, enable_thinking: bool) -> list:
    prepared = []
    for msg in messages:
        item = dict(msg)
        if item.get("role") == "assistant":
            if enable_thinking:
                reasoning = item.pop("reasoning_content", None)
                if reasoning is None:
                    reasoning = item.pop("reasoning", None)
                else:
                    item.pop("reasoning", None)
                item["reasoning_content"] = reasoning or ""
            else:
                item.pop("reasoning_content", None)
                item.pop("reasoning", None)
        prepared.append(item)
    return prepared


def call_model(
        messages: list, 
        *,
        model: str = None,
        tools: list = None,
        tool_choice: str = "auto",
        enable_thinking: bool = None,
        reasoning_effort: str = None,
        return_reasoning: bool = False,
) -> dict:
    """
    调用模型API, 返回消息内容和思考过程。

    参数:
        messages: 唯一必填, 传入消息历史。
        model: 调用模型, 默认为Deepseek。
        tools: 工具列表, 默认不使用。
        tool_choice: 工具选择模式, 默认为auto。
        enable_thinking: 是否开启思考模式, 默认为关闭。
        reasoning_effort: 思考强度, 默认为中等。
        return_reasoning: 是否返回思考过程, 默认为关。
    
    返回:
        dict: {"message": ..., "reasoning": ...}
    """
    if _client is None or MODEL is None:
        raise RuntimeError("api key unavailable")
    if model is None:
        model = MODEL

    if enable_thinking is None:
        enable_thinking = THINKING_ENABLED
    if reasoning_effort is None:
        reasoning_effort = REASONING_EFFORT

    requset_params = {
        "model": model,
        "messages": _prepare_messages(messages, enable_thinking=enable_thinking),
    }

    if tools:
        requset_params["tools"] = tools
        requset_params["tool_choice"] = tool_choice

    if enable_thinking:
        requset_params["extra_body"] = {"thinking": {"type": "enabled"}}
        requset_params["reasoning_effort"] = reasoning_effort
    else:
        requset_params["extra_body"] = {"thinking": {"type": "disabled"}}

    response = _client.chat.completions.create(**requset_params)
    message = response.choices[0].message

    reasoning = getattr(message, "reasoning_content", None)

    return {"message": message, "reasoning": reasoning}

def call_model_stream(messages: list, *, model: str = None, enable_thinking: bool = None, reasoning_effort: str = None):
    if _client is None or MODEL is None:
        raise RuntimeError("api key unavailable")
    if model is None:
        model = MODEL
    if enable_thinking is None:
        enable_thinking = THINKING_ENABLED
    if reasoning_effort is None:
        reasoning_effort = REASONING_EFFORT

    params = {
        "model": model,
        "messages": _prepare_messages(messages, enable_thinking=enable_thinking),
        "stream": True,
    }
    if enable_thinking:
        params["extra_body"] = {"thinking": {"type": "enabled"}}
        params["reasoning_effort"] = reasoning_effort
    else:
        params["extra_body"] = {"thinking": {"type": "disabled"}}

    stream = _client.chat.completions.create(**params)
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue
        thinking_piece = getattr(delta, "reasoning_content", None) or ""
        content_piece = delta.content or ""
        if thinking_piece:
            yield {"type": "thinking", "delta": thinking_piece}
        if content_piece:
            yield {"type": "content", "delta": content_piece}
