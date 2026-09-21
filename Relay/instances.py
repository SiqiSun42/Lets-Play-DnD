"""每用户一个 DSH 实例：独立 DSH_HOME、自己的模型 key、按需起停（spec.md §10.5）。

为什么必须每用户一个 DSH_HOME
------------------------------

DSH 的凭据存储是 **DSH_HOME 级**的：`dsh-credentials-local` 落地为
`<DSH_HOME>/.credentials.yaml`，而 `ctx.credentials.resolve(ref)` 只吃密钥名、
**没有会话/用户维度**（`session.create` 能选 preset、能选 model，但给不了 key）。
所以"每用户一把 key"没有第二条路——只能每用户一个 DSH_HOME。
不这么做的时候，所有实例共用操作者那一把 key，任何登录用户都能烧他的额度。

连接方向
--------

实例与中转的连接是**向外**的（`dsh2server` 插件连 `DSH2SERVER_ENDPOINT`），
所以中转不需要给实例留入站端口。实例自己的 web app 端口用 `--port 0` 交给操作系统选，
省掉端口记账与碰撞。

本模块负责把一个用户从"什么都没有"变成"有实例在线"：

1. 把用户目录铺成合法的 DSH_HOME（profile 复用部署里的 `node_modules`，其余复制）
2. 把该用户的模型 key 写进它自己的 `.credentials.yaml`（0600）
3. 按用户的 `settings.json` 生成一份**每用户 patch**：provider 路由 + 默认模型
4. 生成中转 key 并登记（带 username，中转据此路由到人）
5. 拉起进程、等它上线；以及停止

**没做的事（第二段）**：独立 OS 账号、`iptables` 回环隔离、安装树完整性自检、
systemd 单元。当前之所以还能接受，是因为极简工具面里没有 shell / web——
租户发起不了"伪造 Host 直连别人端口"这类攻击（与 P5-1 是同一条不变量）。
"""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 写进每用户凭据文件的引用名。用固定名字（而不是按 provider 区分）是为了让
# 实例的 patch 只认它自己那一条，不与部署里其它引用（如 DEEPSEEK_API_KEY）混淆。
CREDENTIAL_REF = "LPSD_USER_KEY"

# 每用户 patch 里声明的 pi-ai 路由名。必须是小写连字符标识符。
ROUTE_NAME = "letsplaydnd-user"

# 自动登记的中转 key 的 label 前缀。撤销时只碰这个前缀的行——
# 管理端手工登记的 key（label 不带它）是操作者的东西，自动流程不许删。
AUTO_LABEL_PREFIX = "auto:"

# 铺 profile 时要复制的文件；`node_modules` 用符号链接共享（里面有 100+ 个包，
# 复制一份没有意义，而且运行期 DSH 不写它）。
PROFILE_SKELETON = (
    "cordis.patch.yml",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
)
PROFILE_LINKS = ("node_modules", ".dsh-module-fallback")

# provider → .env 里的变量前缀。与 System/api_client.py 是同一张表。
PROVIDER_ENV_PREFIX = {
    "deepseek": "DEEPSEEK",
    "qwen": "QWEN",
    "openai": "OPENAI",
    "groq": "GROQ",
    "kimi": "KIMI",
}

# 跳过"这个 pid 是不是我们的实例"的命令行核对。默认关：跳过就等于接受
# "pid 被复用后误杀别人进程"的风险，只该在没有 `/proc` 也没有可用 `ps`
# 的环境里开（例如受限的测试沙箱）。
_KILL_UNVERIFIED = os.environ.get(
    "DSH_INSTANCE_KILL_UNVERIFIED", "").strip().lower() in ("1", "true", "yes", "on")


def _read_cmdline(pid: int) -> str | None:
    """尽量取到某进程的命令行；取不到返回 None（调用方按"认不出"处理）。

    Linux 直接读 `/proc`（不起子进程，也不受 PATH 影响）；其它平台退回 `ps`。
    注意：某些受限环境会禁止 `ps`，那时这里返回 None，于是**不会**杀进程。
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        if raw:
            return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        pass
    try:
        proc = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "").strip() or None


def _child_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造**给实例子进程**的环境变量：显式白名单，绝不整份继承。

    为什么不能 `os.environ.copy()`：`dsh-credentials-local` 的凭据解析顺序里
    「继承的进程环境」是会被读的，而且**优先级最高**。Flask 的环境里有
    `FLASK_SECRET_KEY`、`RESEND_API_KEY`，将来还可能有一把 provider 的 key
    （比如服务器上 `export DEEPSEEK_API_KEY=…`）。整份继承就等于把这些交给
    每个用户实例——正好是"每用户一把 key"要挡掉的东西。

    代理变量要放行：被代理的部署里不放行实例就连不上模型端点。
    它们是地址不是密钥（若代理地址里嵌了凭据，那是部署自己的取舍）。

    Args:
        home: 该用户的 DSH_HOME，同时作为子进程的 `HOME`（`~` 展开也落在它自己家里）。
        extra: 调用方额外要加的变量。

    Returns:
        子进程用的完整环境变量字典。
    """
    passthrough = (
        "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
    )
    env = {name: os.environ[name] for name in passthrough if os.environ.get(name)}
    env["HOME"] = str(home)
    env["DSH_HOME"] = str(home)
    if extra:
        env.update(extra)
    return env


@dataclass
class InstanceConfig:
    """起一个用户实例需要的全部外部参数。"""

    users_root: Path
    profiles_source: Path
    dsh_bin: str = "dsh"
    profile: str = "letsplaydnd"
    patches: tuple[Path, ...] = ()
    preset_dir: Path | None = None
    skills_dir: Path | None = None
    endpoint: str | None = None
    host: str = "127.0.0.1"
    start_timeout_s: float = 90.0
    extra_env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, *, repo_root: Path = ROOT, endpoint: str | None = None) -> "InstanceConfig":
        """从环境变量构造。生产用环境变量指定，本地有默认值可直接跑。"""
        # 默认**不**额外加 `--patch`：profile 自带的 `cordis.patch.yml` 里已经有
        # 部署行（agent-presets / MCP / sandbox-policy，见那份文件顶部的说明），
        # 再叠一份仓库里的 `dsh/profile.patch.yml` 会撞 `duplicate loader entry id`。
        # 部署需要额外叠加层时用 `DSH_INSTANCE_PATCHES`（os.pathsep 分隔）。
        raw_patches = os.environ.get("DSH_INSTANCE_PATCHES", "")
        patches = tuple(Path(p) for p in raw_patches.split(os.pathsep) if p.strip()) \
            if raw_patches else ()
        return cls(
            users_root=Path(os.environ.get("DSH_USERS_DIR", str(repo_root / ".dsh-users"))),
            profiles_source=Path(
                os.environ.get("DSH_PROFILE_SOURCE", str(Path.home() / ".dsh" / "profiles"))
            ),
            dsh_bin=os.environ.get("DSH_BIN", "dsh"),
            profile=os.environ.get("DSH_INSTANCE_PROFILE", "letsplaydnd"),
            patches=patches,
            preset_dir=Path(os.environ["DSH_PRESET_DIR"]) if os.environ.get("DSH_PRESET_DIR") else repo_root / "dsh" / "agent-presets",
            skills_dir=Path(os.environ["DSH_SKILLS_DIR"]) if os.environ.get("DSH_SKILLS_DIR") else repo_root / "Skills",
            endpoint=endpoint or os.environ.get("DSH2SERVER_ENDPOINT"),
        )


def provider_route(provider: str) -> dict | None:
    """provider 名 → 它的 OpenAI 兼容端点与模型名（取自 `.env`，与旧路径同源）。

    Returns:
        ``{"provider", "baseURL", "model"}``；provider 未知或缺配置时返回 None。
    """
    prefix = PROVIDER_ENV_PREFIX.get((provider or "deepseek").strip().lower())
    if not prefix:
        return None
    base_url = (os.environ.get(f"{prefix}_URL") or "").strip()
    model = (os.environ.get(f"{prefix}_MODEL") or "").strip()
    if not base_url or not model:
        return None
    return {"provider": provider, "baseURL": base_url, "model": model}


class UserInstances:
    """按需为用户起停 DSH 实例。

    ``credentials_for(username)`` 由调用方注入（返回 ``{"key":..., "provider":...}``），
    因为"密钥怎么解出来"属于 Flask 侧的知识（Fernet + account.db），本模块不该知道。
    """

    def __init__(self, state, store, config: InstanceConfig, credentials_for):
        self.state = state
        self.store = store
        self.config = config
        self.credentials_for = credentials_for
        self._procs: dict[str, subprocess.Popen] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._last_error: dict[str, str] = {}

    # ── 路径 ────────────────────────────────────────────────────

    def home(self, username: str) -> Path:
        """该用户的 DSH_HOME。用户名只允许安全字符，避免拼出工作区之外的路径。"""
        safe = "".join(ch for ch in username if ch.isalnum() or ch in "-_")
        if not safe or safe != username:
            raise ValueError(f"用户名不适合做目录名：{username!r}")
        return self.config.users_root / safe

    def _lock_for(self, username: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(username, threading.Lock())

    # ── 铺 DSH_HOME ─────────────────────────────────────────────

    def _provision(self, username: str) -> Path:
        """幂等地把用户目录铺成一个可用的 DSH_HOME，返回它。

        profile **不整体共享**：DSH 每次启动都会重写 `profiles/<name>/cordis.yml`，
        两个实例写同一个文件是没必要的争用。所以只复制那几个小文件，
        `node_modules` 之类的大件用符号链接指向部署里的那一份。
        """
        cfg = self.config
        home = self.home(username)
        home.mkdir(parents=True, exist_ok=True)
        home.chmod(0o700)

        shared_profile = cfg.profiles_source / cfg.profile
        if not shared_profile.is_dir():
            raise RuntimeError(f"部署里没有这个 profile：{shared_profile}")

        profiles = home / "profiles"
        profiles.mkdir(exist_ok=True)
        # 模块解析兜底槽（@deepseek-ai/* 都在这里），整份共享即可，运行期不写。
        farm = profiles / "node_modules"
        if not farm.exists():
            src = cfg.profiles_source / "node_modules"
            if not src.is_dir():
                raise RuntimeError(f"部署里没有模块兜底槽：{src}")
            farm.symlink_to(src)

        profile_dir = profiles / cfg.profile
        profile_dir.mkdir(exist_ok=True)
        for name in PROFILE_SKELETON:
            src = shared_profile / name
            dst = profile_dir / name
            if src.is_file():
                shutil.copyfile(src, dst)
        for name in PROFILE_LINKS:
            src = shared_profile / name
            dst = profile_dir / name
            if src.exists() and not dst.exists():
                dst.symlink_to(src)
        return home

    def _write_credentials(self, username: str, plaintext_key: str) -> Path:
        """把该用户的模型 key 写进**它自己的**凭据文件（0600）。

        读-改-写而不是覆盖：DSH 自己也会往这个文件里写东西（例如浏览器会话记录），
        整份覆盖会把它弄丢。
        """
        path = self.home(username) / ".credentials.yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        refs = data.get("refs")
        if not isinstance(refs, dict):
            refs = {}
            data["refs"] = refs
        refs[CREDENTIAL_REF] = plaintext_key
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        path.chmod(0o600)
        return path

    def _write_user_patch(self, username: str, route: dict) -> Path:
        """写每用户 patch：把一个 OpenAI 兼容路由指向该用户的端点与模型。

        为什么用 patch 而不是 settings.yaml：`llm-pi-ai.providers` 是**组合**配置，
        而 provider 路由里不能出现明文密钥（`apiKeyEnv` 只写引用名），
        密钥本身留在 `.credentials.yaml`。
        """
        providers = {
            ROUTE_NAME: {
                "displayName": f"LetsPlayDnD ({route['provider']})",
                "apiKeyEnv": CREDENTIAL_REF,
                "api": "openai-completions",
                "baseURL": route["baseURL"],
                "models": [{"id": route["model"]}],
            }
        }
        # safe_dump 从第 0 列开始，而这段要嵌在 `  config:` 之下，所以要整体缩进。
        body = yaml.safe_dump({"providers": providers}, allow_unicode=True, sort_keys=False)
        indented = "".join(f"    {line}" for line in body.splitlines(keepends=True))
        text = (
            "# 由 Relay/instances.py 按该用户的 settings.json 生成，每次启动会覆盖。\n"
            "- id: llm-pi-ai\n"
            "  config:\n"
            f"{indented}"
            "- id: agent-default-model\n"
            "  config:\n"
            f"    provider: {ROUTE_NAME}\n"
            f"    model: {route['model']}\n"
        )
        patch = self.home(username) / "user.patch.yml"
        patch.write_text(text, encoding="utf-8")
        patch.chmod(0o600)
        return patch

    # ── 中转 key ────────────────────────────────────────────────

    def _register_relay_key(self, username: str) -> str:
        """给该用户登记一把新的中转 key。

        每次启动都先撤销该用户名下的旧 key：一个用户只该有一个实例，
        旧 key 留着只会让"哪个实例在线"变得含糊。
        """
        key = "dshk_" + secrets.token_urlsafe(32)
        # 只撤我们自动生成的（`auto:`）：管理端手工登记的 key 是操作者的东西，
        # 不该被自动流程悄悄删掉。
        self.store.remove_user(username, label_prefix=AUTO_LABEL_PREFIX)
        self.store.add(key, label=f"{AUTO_LABEL_PREFIX}{username}", username=username)
        return key

    # ── 起停 ────────────────────────────────────────────────────

    def _spawn(self, username: str, relay_key: str) -> subprocess.Popen:
        cfg = self.config
        home = self.home(username)
        patch = home / "user.patch.yml"
        # ⚠️ 顺序有讲究：`--profile` / `--patch` 是**启动器**的选项，
        # `--host` / `--port` / `--no-open` 是**目的应用**（web）的选项。
        # 启动器选项必须在前，否则会被当成应用的未知选项
        # （踩过：`error: unknown option '--patch'`）。
        cmd = [cfg.dsh_bin, "--profile", cfg.profile]
        for extra in cfg.patches:
            cmd += ["--patch", str(extra)]
        cmd += ["--patch", str(patch)]
        cmd += ["--host", cfg.host, "--port", "0", "--no-open"]

        env = _child_env(home)
        if cfg.endpoint:
            env["DSH2SERVER_ENDPOINT"] = cfg.endpoint
            env["DSH2SERVER_KEY"] = relay_key
        if cfg.preset_dir:
            env["DSH_PRESET_DIR"] = str(cfg.preset_dir)
        if cfg.skills_dir:
            env["DSH_SKILLS_DIR"] = str(cfg.skills_dir)
        env.update(cfg.extra_env)

        log_path = home / "instance.log"
        log = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), env=env,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,   # 独立进程组，停止时能连子孙一起收
        )
        log.close()
        self._procs[username] = proc
        self._pid_file(username).write_text(str(proc.pid), encoding="utf-8")
        return proc

    def _log_tail(self, username: str, lines: int = 15) -> str:
        path = self.home(username) / "instance.log"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(没有日志)"
        return "\n".join(text.strip().splitlines()[-lines:])

    # ── 进程跟踪 ────────────────────────────────────────────────
    #
    # 光靠内存里的 Popen 不够：Flask 一重启，进程表就丢了，遗留的实例
    # **杀不掉**（实测踩到）。所以在用户的 home 里再留一个 pid 文件；
    # 认领进程前先核对它的命令行里带着这个用户的 home，避免 pid 被复用后误杀。

    def _pid_file(self, username: str) -> Path:
        return self.home(username) / "instance.pid"

    def _pid_state(self, username: str) -> tuple[str, int | None]:
        """pid 文件的状态，决定"能不能杀"：

        - ``missing``    ：没有文件
        - ``dead``       ：文件里的进程已经不在了（陈旧，可清）
        - ``unverified`` ：进程活着，但**认不出**是不是我们的（不杀，文件留着）
        - ``foreign``    ：进程活着，但命令行不是我们的（pid 被复用，绝不杀）
        - ``ours``       ：确认是我们的实例

        认身份的依据是命令行里带着这个用户的 home。认不出来时**失败关闭**——
        宁可不杀（用户下次提问会重新拉起），也不误杀别人的进程。
        """
        try:
            pid = int(self._pid_file(username).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return "missing", None
        if pid <= 0:
            return "dead", pid
        try:
            os.kill(pid, 0)
        except OSError:
            return "dead", pid
        # 明确跳过验证的口子：给没有 /proc 也没有可用 ps 的环境（例如受限的测试沙箱）。
        # 默认关，因为跳过就等于接受"pid 被复用后误杀"的风险。
        if _KILL_UNVERIFIED:
            return "ours", pid
        cmdline = _read_cmdline(pid)
        if cmdline is None:
            return "unverified", pid
        return ("ours" if str(self.home(username)) in cmdline else "foreign"), pid

    def _kill_current(self, username: str) -> bool:
        """把这个用户名下正在跑的实例收掉（无论是不是本进程拉起的）。

        返回是否真的发过终止信号。
        """
        proc = self._procs.pop(username, None)
        if proc is not None and proc.poll() is None:
            self._terminate_pid(proc.pid)
            self._pid_file(username).unlink(missing_ok=True)
            return True

        state, pid = self._pid_state(username)
        if state == "ours" and pid is not None:
            self._terminate_pid(pid)
            self._pid_file(username).unlink(missing_ok=True)
            return True
        if state == "foreign":
            # pid 被复用了：文件是陈旧的，但那个进程不是我们的。
            print(f"[instances] {username} 的 pid 文件指向的不是我们的实例，"
                  f"已丢弃该文件、不发送信号", flush=True)
            self._pid_file(username).unlink(missing_ok=True)
        elif state == "dead":
            self._pid_file(username).unlink(missing_ok=True)
        # missing / unverified：什么都不做（unverified 保留文件，等能认出来时再收）
        return False

    def _terminate_pid(self, pid: int, timeout_s: float = 10.0) -> None:
        """先 SIGTERM 整个进程组，超时再 SIGKILL。"""
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.2)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def ensure(self, username: str) -> str | None:
        """确保该用户有实例在线，返回它的 instance_id。

        已经在线就直接返回（这是常态，也是最便宜的路径）。否则铺 DSH_HOME、
        写凭据与 patch、登记 key、拉起进程，等到上线为止。
        """
        online = self.state.instance_for_user(username)
        if online:
            return online

        with self._lock_for(username):
            online = self.state.instance_for_user(username)
            if online:
                return online

            creds = self.credentials_for(username)
            plaintext = (creds or {}).get("key")
            if not plaintext:
                raise RuntimeError(f"用户 {username} 没有可用的模型 API Key")

            route = provider_route((creds or {}).get("provider"))
            if route is None:
                raise RuntimeError(
                    f"用户 {username} 的 provider 无法解析（settings.json 的 model="
                    f"{(creds or {}).get('provider')!r}），"
                    f"或 .env 里缺少对应的 *_URL / *_MODEL"
                )

            home = self._provision(username)
            self._write_credentials(username, plaintext)
            self._write_user_patch(username, route)
            relay_key = self._register_relay_key(username)

            # 拉起前先收掉这个用户名下可能还活着的实例（含上一个 Flask 进程遗留的）：
            # 反正 key 要重新登记，留着旧的只会让"哪个实例算这个用户的"变得含糊。
            self._kill_current(username)
            proc = self._spawn(username, relay_key)

            deadline = time.monotonic() + self.config.start_timeout_s
            while time.monotonic() < deadline:
                if self.state.instance_for_user(username):
                    return self.state.instance_for_user(username)
                if proc.poll() is not None:
                    err = (f"实例进程已退出（code={proc.returncode}）：\n"
                           + self._log_tail(username))
                    self._last_error[username] = err
                    raise RuntimeError(err)
                time.sleep(0.5)

            err = (f"实例 {self.config.start_timeout_s:.0f}s 内未上线（{home}）：\n"
                   + self._log_tail(username))
            self._last_error[username] = err
            raise RuntimeError(err)

    @staticmethod
    def _terminate(proc: subprocess.Popen, timeout_s: float = 10.0) -> None:
        """（保留给直接持有 Popen 的调用方）转调按 pid 的收尾。"""
        UserInstances._terminate_pid(proc.pid, timeout_s)

    def stop(self, username: str) -> bool:
        """停掉该用户的实例并撤销**我们自动登记**的中转 key。返回是否真的停了一个。"""
        with self._lock_for(username):
            stopped = self._kill_current(username)
            self.store.remove_user(username, label_prefix=AUTO_LABEL_PREFIX)
            return stopped

    def status(self) -> list[dict]:
        """本地记录：谁有进程、上次失败是什么。管理面板用。"""
        out = []
        for username, proc in self._procs.items():
            out.append({
                "username": username,
                "pid": proc.pid,
                "alive": proc.poll() is None,
                "online": bool(self.state.instance_for_user(username)),
                "home": str(self.home(username)),
                "lastError": self._last_error.get(username),
            })
        return out
