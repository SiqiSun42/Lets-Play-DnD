from .consult.rag_tools_zh import rag_tools as rag_tools_zh
from .consult.rag_tools_en import rag_tools as rag_tools_en
from .game_zh.classfiy_tool import (
    classify_tool as classify_tool_zh,
    normalize_classify_category as normalize_classify_category_zh,
)
from .dice.dice_tool_zh import dice_tool as dice_tool_zh
from .dice.dice_battle_tool_zh import dice_battle_tool as dice_battle_tool_zh
from .game_zh.check_tool import check_tool as check_tool_zh, action_tool as action_tool_zh
from .game_zh.panel_tool import panel_tool as panel_tool_zh
from .game_zh.update_tool import (
    update_tool as update_tool_zh,
    parse_update_plan as parse_update_plan_zh,
)
from .mcp.mcp_tools import (
    get_tools as get_mcp_tools,
    get_update_tools,
    get_update_location_tools,
    execute_tool as execute_mcp_tool,
)
