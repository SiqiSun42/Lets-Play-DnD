import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _read_prompt(filename: str) -> str:
    """读取提示词文件"""
    file_path = os.path.join(BASE_DIR, filename)
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

DECISION_PROMPT = _read_prompt('decision.md')
OUTPUT_PROMPT = _read_prompt('output.md')