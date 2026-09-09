import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

# 全局变量，存储API客户端和配置信息
_client = None
MODEL = None
THINKING_ENABLED = None
REASONING_EFFORT = None

def configure_client(*, api_key: str, provider: str):
    global _client, MODEL, THINKING_ENABLED, REASONING_EFFORT
    # 检查api_key是否为空
    if not api_key:
        raise ValueError("api_key is empty")

    # 加载项目根目录下的.env环境变量文件
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    # 根据provider类型映射到对应的环境变量前缀
    env_prefix = {
        "deepseek": "DEEPSEEK",
        "qwen": "QWEN",
        "openai": "OPENAI",
        "groq": "GROQ",
        "kimi": "KIMI",
    }.get(provider)
    # 检查provider是否支持
    if not env_prefix:
        raise ValueError(f"unsupported provider: {provider}")

    # 获取环境变量中的base_url和model_name
    base_url = os.getenv(f"{env_prefix}_URL")
    model_name = os.getenv(f"{env_prefix}_MODEL")
    # 检查base_url和model_name是否存在
    if not base_url or not model_name:
        raise ValueError(f"{env_prefix}_URL or {env_prefix}_MODEL missing in .env")
    
    # 初始化OpenAI客户端
    _client = OpenAI(api_key=api_key, base_url=base_url)
    MODEL = model_name
    # 从环境变量获取思考模式和推理难度设置
    THINKING_ENABLED = os.getenv(f"{env_prefix}_THINKING_ENABLED", "true").lower() == "true"
    REASONING_EFFORT = os.getenv(f"{env_prefix}_REASONING_EFFORT", "medium").strip().strip('"')

def clear_client():
    global _client, MODEL, THINKING_ENABLED, REASONING_EFFORT
    # 重置所有全局变量
    _client = None
    MODEL = None
    THINKING_ENABLED = None
    REASONING_EFFORT = None


def _prepare_messages(messages: list, *, enable_thinking: bool) -> list:
    prepared = []
    # 遍历每条消息进行处理
    for msg in messages:
        item = dict(msg)
        # 只处理assistant角色的消息
        if item.get("role") == "assistant":
            if enable_thinking: # 思考模式如果开，信息不存在reasoning容易报错（不知为何？），但reasoning未必保存在上下文，开销也大。所以手动替换为空
                reasoning = item.pop("reasoning_content", None)
                if reasoning is None:
                    reasoning = item.pop("reasoning", None)
                else:
                    item.pop("reasoning", None)
                # 确保reasoning_content字段存在
                item["reasoning_content"] = reasoning or ""
            else:
                # 思考模式禁用：直接移除所有reasoning相关字段即可
                item.pop("reasoning_content", None)
                item.pop("reasoning", None)
        prepared.append(item)
    return prepared


def _normalize_usage(usage) -> dict:
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


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
        dict: {"message": ..., "reasoning": ..., "usage": ...}
    """
    # 检查客户端是否已初始化
    if _client is None or MODEL is None:
        raise RuntimeError("api key unavailable")
    if model is None: # 使用全局配置作为默认值
        model = MODEL

    if enable_thinking is None:
        enable_thinking = THINKING_ENABLED
    if reasoning_effort is None:
        reasoning_effort = REASONING_EFFORT

    # 构建API请求的参数字典，目前只有OpenAI系
    requset_params = {
        "model": model,
        "messages": _prepare_messages(messages, enable_thinking=enable_thinking),
    }

    # 如果提供了工具，添加工具相关参数
    if tools:
        requset_params["tools"] = tools
        requset_params["tool_choice"] = tool_choice

    # 根据enable_thinking设置思考模式的extra_body参数
    if enable_thinking:
        requset_params["extra_body"] = {"thinking": {"type": "enabled"}}
        requset_params["reasoning_effort"] = reasoning_effort
    else:
        requset_params["extra_body"] = {"thinking": {"type": "disabled"}}

    # 调用API获取响应
    response = _client.chat.completions.create(**requset_params)
    message = response.choices[0].message

    # 从响应中提取思考过程内容
    reasoning = getattr(message, "reasoning_content", None)

    # 返回消息、思考过程和使用统计信息
    return {
        "message": message,
        "reasoning": reasoning,
        "usage": _normalize_usage(getattr(response, "usage", None)),
    }

def call_model_stream(
        messages: list,
        *,
        model: str = None,
        enable_thinking: bool = None,
        reasoning_effort: str = None,
        include_usage: bool = False,
):
    if _client is None or MODEL is None:
        raise RuntimeError("api key unavailable")
    if model is None:
        model = MODEL
    if enable_thinking is None:
        enable_thinking = THINKING_ENABLED
    if reasoning_effort is None:
        reasoning_effort = REASONING_EFFORT

    # 构建流式API请求参数，和call_model差不多
    params = {
        "model": model,
        "messages": _prepare_messages(messages, enable_thinking=enable_thinking),
        "stream": True,
    }

    # 如果需要返回使用token统计，添加stream_options参数
    if include_usage:
        params["stream_options"] = {"include_usage": True}

    # 配置思考模式，差不多
    if enable_thinking:
        params["extra_body"] = {"thinking": {"type": "enabled"}}
        params["reasoning_effort"] = reasoning_effort
    else:
        params["extra_body"] = {"thinking": {"type": "disabled"}}

    # 创建流对象并开始遍历每个chunk
    stream = _client.chat.completions.create(**params)
    for chunk in stream:
        # 从chunk中提取使用统计信息（如果有）
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            yield {"type": "usage", "usage": _normalize_usage(usage)}

        # 获取当前chunk的delta信息
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue

        # 分别提取思考过程和生成内容的片段
        thinking_piece = getattr(delta, "reasoning_content", None) or ""
        content_piece = delta.content or ""

        # 逐个yield不同类型的数据块，思考和内容
        if thinking_piece:
            yield {"type": "thinking", "delta": thinking_piece}
        if content_piece:
            yield {"type": "content", "delta": content_piece}
