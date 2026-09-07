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
DM_NOTE_ZH_PROMPT = _read_prompt('game_zh/0. dm note.md')
CLASSIFY_ZH_PROMPT = _read_prompt('game_zh/1.classify.md')
PREPARE_ZH_PROMPT = _read_prompt('game_zh/2.prepare.md')
META_ZH_PROMPT = _read_prompt('game_zh/3.0 meta.md')
CHECK_ZH_PROMPT = _read_prompt('game_zh/3.1 check.md')
ACTION_ZH_PROMPT = _read_prompt('game_zh/3.2 action.md')
INTERACTION_ZH_PROMPT = _read_prompt('game_zh/3.3 interaction.md')
EXPLORATION_ZH_PROMPT = _read_prompt('game_zh/3.4 exploration.md')
UPDATE_ZH_PROMPT = _read_prompt('game_zh/4. update.md')
UPDATE_INVENTORY_STATUS_ZH_PROMPT = _read_prompt('game_zh/4.1 update_inventory_status.md')
UPDATE_LOCATION_ZH_PROMPT = _read_prompt('game_zh/4.2 update_location.md')
BATTLE_INIT_ZH_PROMPT = _read_prompt('battle_zh/1.1 trigger_battle.md')
BATTLE_BASIC_INFO_ZH_PROMPT = _read_prompt('battle_zh/1.2 basic_info.md')
BATTLE_PRE_CHECK_ZH_PROMPT = _read_prompt('battle_zh/2.1 pre_check.md')
BATTLE_PRE_RESULT_ZH_PROMPT = _read_prompt('battle_zh/2.2 pre_result.md')
BATTLE_ALLIES_CHECK_ZH_PROMPT = _read_prompt('battle_zh/3.1 allies_check.md')
BATTLE_ENEMIES_ACTION_ZH_PROMPT = _read_prompt('battle_zh/4.1 enemies_action.md')
BATTLE_ENEMIES_CHECK_ZH_PROMPT = _read_prompt('battle_zh/4.2 enemies_check.md')
BATTLE_SECOND_CHECK_ZH_PROMPT = _read_prompt('battle_zh/5.1 second_check.md')
BATTLE_ACTION_ZH_PROMPT = _read_prompt('battle_zh/5.2 action.md')
BATTLE_WRITE_RESULT_ZH_PROMPT = _read_prompt('battle_zh/6. write_result.md')
BATTLE_TRIGGER_ENDING_ZH_PROMPT = _read_prompt('battle_zh/7.1 trigger_ending.md')
BATTLE_ALL_DEAD_ZH_PROMPT = _read_prompt('battle_zh/8.1 all_dead.md')
BATTLE_CHARACTER_CHECK_ZH_PROMPT = _read_prompt('battle_zh/9.1 character_check.md')
BATTLE_LOOT_ZH_PROMPT = _read_prompt('battle_zh/9.2 loot.md')
BATTLE_UPDATE_ENDING_ZH_PROMPT = _read_prompt('battle_zh/10. update_ending.md')

# 英文提示词
DECISION_EN_PROMPT = _read_prompt('consult/decision-en.md')
OUTPUT_EN_PROMPT = _read_prompt('consult/output-en.md')
