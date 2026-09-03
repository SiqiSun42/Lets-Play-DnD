import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _read_prompt(filename: str) -> str:
    """读取提示词文件"""
    file_path = os.path.join(BASE_DIR, filename)
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

# 中文提示词
DECISION_ZH_PROMPT = _read_prompt('consult/decision-zh.md')
OUTPUT_ZH_PROMPT = _read_prompt('consult/output-zh.md')
CLASSIFY_ZH_PROMPT = _read_prompt('game_zh/1.classify.md')
PREPARE_ZH_PROMPT = _read_prompt('game_zh/2.prepare.md')

# 英文提示词
DECISION_EN_PROMPT = _read_prompt('consult/decision-en.md')
OUTPUT_EN_PROMPT = _read_prompt('consult/output-en.md')