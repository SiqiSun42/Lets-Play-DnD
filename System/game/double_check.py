import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

DB_DIR = ROOT / "Templates" / "example"


def double_check(username, save_id):
    save_dir = (
        ROOT / "Account" / username / "Saves" / save_id / "data" 
    )
    world_dir = (
        save_dir / "world"
    )

    map_src_file = DB_DIR / "map.json"
    map_dst_file = world_dir / "map.json"

    loc_src_file = DB_DIR / "冒险杂货店.md"
    loc_dst_file = world_dir / "冒险杂货店.md"

    cur_src_file = DB_DIR / "current_info.json"
    cur_dst_file = save_dir / "current_info.json"

    shutil.copy2(map_src_file, map_dst_file)
    shutil.copy2(loc_src_file, loc_dst_file)
    shutil.copy2(cur_src_file, cur_dst_file)

if __name__ == "__main__":
    double_check("admin", "game_20260914211011")