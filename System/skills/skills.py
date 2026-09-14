from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = ROOT / "Skills" 

def load_skills_meta(skill_names: list[str]) -> list[dict]:
    """
    加载指定 skills 的 frontmatter（name + description），返回 system messages 列表
    """
    messages = []
    for skill_name in skill_names:
        skill_path = Path(SKILLS_DIR) / skill_name / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        
        parts = content.split("---")
        if len(parts) < 3:
            continue
        frontmatter = parts[1].strip()
        
        messages.append({"role": "system", "content": frontmatter})
    
    return messages

def load_skill(skill_name: str) -> str:
    """
    加载指定 skill 的 SKILL.md 完整内容
    """
    skill_path = Path(SKILLS_DIR) / skill_name / "SKILL.md"
    with open(skill_path, 'r', encoding='utf-8') as f:
        return f.read()