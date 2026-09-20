"""存档快照：把每回合的存档状态提交到一个**工作区之外**的裸 git 库。

为什么快照存在工作区之外
------------------------

模型对工作区有写权限（`workspace-write` 围栏只保证"只能写这里"，不保证"不写坏"）。
若把 `.git` 放进存档目录，模型（或被提示注入引导的模型）理论上能改写历史，
快照就失去意义。所以裸库放在模型够不到的路径，例如
`/var/lib/letsplaydnd/history/`。

为什么只快照 `data/`
--------------------

存档目录里还有 `chat.db`（对话记录，二进制且每回合都变）。把它一起提交会让
仓库迅速膨胀，而且回滚存档时未必想丢对话。调用方按需选择 `work_tree`——
通常传 `<存档>/data`。

用法：

    snaps = SaveSnapshots("/var/lib/letsplaydnd/history")
    snaps.commit(Path("Account/alice/Saves/g1/data"), "turn 12")
    snaps.history(Path("Account/alice/Saves/g1/data"))
    snaps.rollback(Path("Account/alice/Saves/g1/data"), "HEAD~1")
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

# 提交需要的身份；写在仓库局部配置里，不动用户的全局 git 配置。
_GIT_NAME = "letsplaydnd-snapshot"
_GIT_EMAIL = "snapshot@letsplaydnd.invalid"


class SnapshotError(RuntimeError):
    pass


class SaveSnapshots:
    """按工作目录（存档 `data/`）维护一颗裸库。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── 内部 ────────────────────────────────────────────────────

    def git_dir(self, work_tree: str | Path) -> Path:
        """该工作目录对应的裸库路径。

        用绝对路径的 sha1 命名，避免把用户路径塞进文件名（也天然防目录穿越）。
        """
        key = hashlib.sha1(str(Path(work_tree).resolve()).encode("utf-8")).hexdigest()
        return self.root / f"{key}.git"

    def _git(self, work_tree: str | Path, *args: str, check: bool = True):
        git_dir = self.git_dir(work_tree)
        cmd = ["git", f"--git-dir={git_dir}", f"--work-tree={Path(work_tree).resolve()}"]
        proc = subprocess.run(
            [*cmd, *args],
            capture_output=True, text=True,
        )
        if check and proc.returncode != 0:
            raise SnapshotError(
                f"git {' '.join(args)} 失败（{proc.returncode}）：{proc.stderr.strip()}"
            )
        return proc

    # ── 对外 ────────────────────────────────────────────────────

    def ensure(self, work_tree: str | Path) -> Path:
        """确保该工作目录的裸库存在，返回其路径。"""
        work_tree = Path(work_tree)
        git_dir = self.git_dir(work_tree)
        if not git_dir.is_dir():
            git_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "init", "--bare", "--quiet", str(git_dir)],
                capture_output=True, text=True, check=True,
            )
            self._git(work_tree, "config", "user.name", _GIT_NAME)
            self._git(work_tree, "config", "user.email", _GIT_EMAIL)
        if not work_tree.is_dir():
            raise SnapshotError(f"工作目录不存在：{work_tree}")
        return git_dir

    def _tree_of(self, work_tree: str | Path, rev: str) -> str | None:
        proc = self._git(work_tree, "rev-parse", f"{rev}^{{tree}}", check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    def _read_position(self, work_tree: str | Path) -> str | None:
        """读"当前位置"（最近一次提交或回滚到的版本）。

        为什么不直接拿 HEAD 当基准：回滚**不动 HEAD**（这样历史不丢、能再往回滚），
        所以回滚之后 HEAD 是旧尖端、工作树是目标版本。若仍拿 HEAD 比较，
        "回滚后本轮没改任何东西"会被误判成"有变化"，从而生成一个与目标版本
        完全相同的重复提交。故用 POSITION 单独记录基准点。
        """
        path = self.git_dir(work_tree) / "POSITION"
        if path.is_file():
            rev = path.read_text(encoding="utf-8").strip()
            if rev:
                return rev
        return None

    def _write_position(self, work_tree: str | Path, rev: str) -> None:
        (self.git_dir(work_tree) / "POSITION").write_text(rev + "\n", encoding="utf-8")

    def commit(self, work_tree: str | Path, message: str) -> str | None:
        """提交当前状态；与"当前位置"相比无变化时返回 None。"""
        self.ensure(work_tree)
        self._git(work_tree, "add", "-A", ".")
        tree = self._git(work_tree, "write-tree").stdout.strip()
        # 基准点：优先 POSITION；老库（无 POSITION）退回 HEAD。
        base = self._read_position(work_tree) or "HEAD"
        if self._tree_of(work_tree, base) == tree:
            return None
        # --allow-empty：模型可能恰好把文件改回上一个提交的样子。此时索引与 HEAD
        # 相同，普通 commit 会直接报错；但"位置"确实移动了，必须记下来。
        self._git(work_tree, "commit", "--quiet", "--allow-empty", "-m", message)
        rev = self._git(work_tree, "rev-parse", "HEAD").stdout.strip()
        self._write_position(work_tree, rev)
        return rev

    def history(self, work_tree: str | Path, limit: int = 50) -> list[dict]:
        """最近的提交，新→旧。"""
        self.ensure(work_tree)
        proc = self._git(
            work_tree, "log", f"-{int(limit)}",
            "--pretty=format:%H%x1f%h%x1f%ct%x1f%s", check=False,
        )
        out = []
        for line in proc.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                out.append({"rev": parts[0], "short": parts[1],
                            "time": int(parts[2]), "message": parts[3]})
        return out

    def rollback(self, work_tree: str | Path, rev: str = "HEAD") -> None:
        """把工作目录恢复到某个提交，**历史保留**（回滚本身可再提交）。

        用 ``read-tree --reset -u`` 而不是 ``checkout``：
        - ``checkout <rev> -- .`` 会恢复已跟踪文件，但**不会删除**目标版本里不存在的
          文件（它们仍在索引里，``clean`` 也清不掉）；
        - ``checkout <rev>`` 会让 HEAD 进入 detached 状态；
        - ``read-tree --reset -u`` 同时重置索引与工作树、删掉多余文件，且**不动 HEAD**，
          因此后续提交会在原历史上继续，随时可以再往前滚。
        """
        self.ensure(work_tree)
        self._git(work_tree, "read-tree", "--reset", "-u", rev)
        # 清掉从来未被跟踪过的残留文件
        self._git(work_tree, "clean", "-fdq", check=False)
        resolved = self._git(work_tree, "rev-parse", f"{rev}^{{commit}}").stdout.strip()
        self._write_position(work_tree, resolved)
