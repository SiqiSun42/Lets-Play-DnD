# LetsPlayDnD × DSH 迁移 Spec

> 配套文档：`update.md`（调研过程与证据）。本文件是执行方案。
> 备份基点：`main` @ `00cbb7f`

---

## 1. 目标

把手搓的 agent 编排换成 DSH：

| 现在 | 目标 |
|---|---|
| `System/consult`、`System/game` 里的 Python DAG | SKILL.md 描述的流程，模型自行推进 |
| `Prompts/*.md` 按 stage 加载 | SKILL.md 正文 + `references/` 资源 |
| 19 个 function-calling 工具（多数是结构化输出壳） | 极简工具面：`read` / `write` / `skill` + 2 个 MCP 工具 |
| 手写 `if func_name == ...` 分发 | DSH 工具分派 |

**范围**：consult 优先，game 常规回合其次，battle 暂缓（流程本身未完成）。
**语言**：仅中文（bilingual 暂缓，见 §6）。

---

## 2. 目标架构

```
浏览器 (UI/)
   │  现有 SSE（前端不改）
   ▼
Flask (server.py) ── 用户 / 账号 / 存档元数据 ──▶ account.db
   │                                              Account/<user>/Saves/<id>/
   │  会话管理 + 事件翻译（session.event → 现有事件格式）
   ▼
DSH 实例（每用户一个）  profile: 自定义 patch（§4 P3）
   │  MCP over HTTP
   ▼
MCP 服务（常驻单进程）── import ──▶ RAG/ + Dice/
```

---

## 3. 部署拓扑 —— 先纠正一个理解

### 3.1 DSH 不会去 GitHub 拉 skills

**核心事实：`dsh-skill-filesystem` 只扫服务器本地目录。**

它的扫描根（按 rank）：

```
100  <projectRoot>/.dsh/skills
200  <projectRoot>/.agents/skills
300  customSkillDirs（可配置）
400  <dshHome>/skills
500  <agentsHome>/skills
```

`projectRoot` = 含 `.git` 的最近祖先目录。**没有任何"从 GitHub 导入"的机制**——`dsh-skill` 注册表理论上接受远程 provider，但那是要自己写插件的。

所以实际链路仍然是：

```
本地开发 → git push → 服务器 git pull → DSH 从服务器本地目录扫到 skills
```

（例外：`dsh plugin add github:<user>/<repo>` 会把一个包装进 profile。但那要求 skills 以插件形式打包，而我们已经决定不打包。）

### 3.2 所以「分开」是逻辑上的，不是物理上的

你的直觉方向对，但要精确：

| | 说明 |
|---|---|
| ✅ 对 | Flask + Account + RAG 是**应用**；Skills 是**agent 行为配置**。两者变更节奏不同、职责不同，是**不同的 artifact** |
| ❌ 需修正 | 它们**都在同一台服务器上**。Skills 不是"不用上传"，而是"不用经过 Flask"——DSH 直接从文件系统读，与 Flask 无关 |
| ⚠️ 补充 | DSH 只是**不通过 Flask** 拿 skills。文件本身还是得在服务器上 |

### 3.3 建议：先放同一个 repo

**理由**：

- `dsh-skill-filesystem` 默认 `watch: true`，**skill 改动热加载**——编辑 `SKILL.md` 或 `references/` 后，下一个模型步骤就生效，**不用重启 DSH**
- 一次 `git pull` 更新全部；skill 改动不触发 Flask 重启
- 单人项目，没有并行迭代的协调需求
- 以后要拆是**改一行配置**的事，不是重构

**拆分时机**：当 skill 迭代频繁到"每次都要连带部署应用"成为负担时——目前不是。

### 3.4 服务器布局

```
/opt/letsplaydnd/                    ← 一个 repo，git pull 更新
  server.py
  System/  UI/  RAG/  Dice/
  Skills/
    consult-zh/
      SKILL.md
      references/                    ← 现在的提示词
  MCP/
    mcp_server.py                    ← RAG + 骰子 的 MCP 服务
  dsh/
    profile.patch.yml                ← 共享的 profile 覆盖
    units/                           ← systemd 单元模板

/var/lib/letsplaydnd/history/        ← 存档快照裸库（模型够不到，见 §4 P5）
/var/lib/letsplaydnd/users/<name>/   ← 每用户 DSH_HOME（0700）
```

### 3.5 共享配置：用 `--patch`

每用户有独立 `DSH_HOME`，意味着 profile 配置会重复 N 份。用**共享 patch 文件**避免：

```bash
dsh --profile sdk --patch /opt/letsplaydnd/dsh/profile.patch.yml
```

patch 里放与用户无关的东西：`customSkillDirs`、工具 allowlist、MCP server 地址、模型路由。
每用户私有的部分（凭据、`DSH_HOME`）走环境变量。

### 3.6 更新后要不要重启 DSH？

**Skill 和插件不是一回事。**

| 更新什么 | 重启 DSH？ | 依据 |
|---|---|---|
| Skill 正文（`SKILL.md` body） | ❌ 不用 | "每次加载都会重新读取当前文件" |
| Skill frontmatter（name / description） | ❌ 不用 | "下一个模型步骤触发目录刷新" |
| `references/` 等资源 | ❌ 不用 | 模型自己 `read`，本就没有缓存 |
| MCP 服务代码（RAG / Dice） | ❌ 不用 | 重启 MCP 服务即可，DSH 自动重连并刷新工具集 |
| profile patch（工具集 / MCP 地址 / skill 目录） | ⚠️ 看 `patchReload` | **自定义 profile 默认 `live` → 不用**；随附 `sdk` / `acp` 模板是 `startup` → 要 |
| 装卸插件包（`dsh plugin add`） | ✅ 要 | bundle 名单变化 |
| DSH 本体升级 | ✅ 要 | |

**关键**：`dsh-app-boot` 文档说"**自定义 profile 省略 reload 策略时保留历史 `live` 默认值**"。本项目用的是自建 profile，所以默认就是 `live`——**patch 文件能实时重组合，不用重启**。随附的 `web` / `sdk` / `acp` 模板才强制 `startup`。这是自建 profile 的一个实际好处。

`patchReload: live` 原文："会监视两份用户 patch 文件：有效编辑无需重启即可重新组合，被拒绝的编辑则让最后一个可用应用继续运行。"

⚠️ **一个坑**：MCP 断连有重试预算。`dsh-mcp-client` 默认 `reconnect.maxAttempts: 10`，延迟从 500 ms 翻倍、上限 30 s——累计**约 2.5 分钟**。超过预算后该服务器的工具会被移除、重连停止，直到重载配置或重启 harness。所以 MCP 服务重启要快；长时间停机就得重启 DSH。

---

## 4. 执行阶段

按依赖排序。每个阶段独立可验收、可回退。

### P0 · 技术验证（spike）

**目的**：证实/证伪核心假设，产出可丢弃。

**做**：

1. 起 `dsh --profile sdk` 子进程，独立 `DSH_HOME` + 环境变量注入测试 key
2. 用 Python SDK 发一句 prompt，把 `session.event` 原样打出来
3. 确认三件事：思考是否逐 token 流出、工具调用事件长什么样、有没有我们还需要的事件类型

**验收**：能看到逐步的 thinking 与 content 事件；能收到 tool_call 事件。
**依赖**：无。**不改任何现有代码。**

> 这一步若能证伪"DSH 能驱动这个游戏流程"，后面全部作废——所以放最前面。

### P1 · MCP 服务

**做**：

1. `MCP/mcp_server.py`，HTTP transport，暴露两个工具：
   - `search_rules` → `from RAG import ...`
   - `roll_dice` → `from Dice.dice import roll_dice`
2. systemd 单元，常驻，固定端口（仅 127.0.0.1）

**为什么 HTTP 不是 stdio**：每用户一个 DSH 实例，stdio 会让每个实例 spawn 自己的 MCP server → **N 份 Chroma + N 份 embedding 模型**。现有 Flask 里 RAG 是共享的，改 stdio 是回退。HTTP 共享一份。

**验收**：MCP 客户端能调通两个工具；进程常驻，RAG 只加载一次；重启后自动恢复。
**依赖**：无（可独立于 DSH 完成）。

### P2 · consult skills（中文）

**做**：

1. `Skills/consult-zh/SKILL.md`：流程总纲 + 指向 references
2. `Skills/consult-zh/references/`：把 `Prompts/consult/*.md` 搬进来
3. 三段式（判断 → 查规则 → 输出）——`System/consult/consult.py:334` 那段**被注释掉的 3 段版**就是雏形

**验收**：本地 DSH 手动对话，能走完"判断是否需要查规则 → 调 `search_rules` → 输出"，且规则引用正确。
**依赖**：P1（需要 `search_rules`）。

### P3 · 最小 profile

**做**：`dsh/profile.patch.yml`，只挂需要的：

```yaml
- insert:
    # ... llm / session / agent / system-prompt 等必需内核
    #     模板参考 dsh-sdk-minimal/cordis.patch.yml

    - id: sandbox-policy
      name: '@deepseek-ai/dsh-sandbox-policy'
    - id: fs
      name: '@deepseek-ai/dsh-fs-sandbox'
      config:
        cwd: <存档工作区>
    - id: fs-observation-policy
      name: '@deepseek-ai/dsh-fs-observation-policy'
    - id: tool-fs
      name: '@deepseek-ai/dsh-tool-fs'
    - id: skill
      name: '@deepseek-ai/dsh-tool-skill'
    - id: skill-fs
      name: '@deepseek-ai/dsh-skill-filesystem'
      config:
        customSkillDirs: ['/opt/letsplaydnd/Skills']
    - id: mcp
      name: '@deepseek-ai/dsh-mcp-client'
      # ... 指向 MCP 服务的 HTTP 地址

    # 全部不挂：bash / pwsh / jobs / fs-search / subagent /
    #          workflow / todo / goal / ralph / web
```

**本阶段不写任何 DSH 插件代码**：

- profile patch 是 **YAML 配置**，组合的是现成官方包，不是新插件
- `dsh-tool-fs`、`dsh-tool-skill`、`dsh-skill`、`dsh-skill-filesystem`、`dsh-fs-sandbox`、`dsh-sandbox-policy`、`dsh-fs-observation-policy` **都已在 `dsh-base` 的依赖与 patch 里**，直接引用即可
- 唯一需要**安装**（非开发）的是 `@deepseek-ai/dsh-mcp-client`——**它不在 base 中**：

  ```bash
  dsh plugin --profile <name> add @deepseek-ai/dsh-mcp-client
  ```

- 工具能力全部由 **MCP（Python 脚本）** 提供，不是 DSH 插件

> 整个方案**零 DSH 插件开发**。原先考虑过的两个插件（读围栏的 path-guard、多用户 key 的 LLM adapter）已被 systemd 命名空间与「每用户一实例」取代。

**验收**：

- 模型可见工具**恰好**是 `read` / `write` / `edit` / `skill` / `mcp__*`
- 尝试写工作区外的路径 → `FS_SANDBOX_DENIED`
- 确认模型**无法**自行提权沙箱模式（无 approver 时应 fail-closed）

**依赖**：P1（MCP 地址）、P2（skills 目录）。

### P4 · Flask ↔ DSH 桥

**做**：

1. **实例管理**：每用户一个 DSH 进程——分配端口、独立 `DSH_HOME`、注入该用户 API Key（从 `account.db` 解密）、生命周期与重启
2. **事件翻译**：读 DSH 的 `session.event`，转成前端现有的事件 JSON
3. 前端**不改**

**验收**：前端零改动，consult 走 DSH 也能正常出字与显示思考。
**依赖**：P3。
**参考**：[dsh-server-deployment](https://github.com/AnkoCD/dsh-server-deployment) 的 `gateway/userctl.js` 与 `docs/multi-user-isolation.md`。

### P5 · 安全加固

**做**：

1. **systemd 命名空间**（读隔离）：

   ```ini
   InaccessiblePaths=/opt/letsplaydnd/.env
   InaccessiblePaths=/opt/letsplaydnd/account.db
   ProtectHome=yes
   ProtectProc=invisible
   ProcSubset=pid
   ReadOnlyPaths=/opt/letsplaydnd
   NoNewPrivileges=yes
   ```

   `ProtectProc` / `ProcSubset` 是必需的——否则同账号下仍可读 `/proc/<flask_pid>/environ` 拿密钥。需较新的 systemd。

2. **存档快照**（工作区**之外**的裸库，模型够不到）：

   ```bash
   git --git-dir=/var/lib/letsplaydnd/history/<save_id>.git \
       --work-tree=<存档目录> add -A
   git --git-dir=... commit -m "turn N"
   ```

3. **回环租户隔离**（若多用户实例并存在 127.0.0.1）：iptables OUTPUT，每个实例只能连自己的端口。否则任一租户可伪造 Host 直连他人端口窃取 API Key。

**验收**：DSH 进程内读不到 `.env` 与 `account.db`；存档可回滚到任意回合。
**依赖**：P4。

### P6 · game 流程迁移

**做**：把 `System/game/game_zh.py` 的 DAG 改写成 skill。

- 按类别分派提示词 → 交给模型，在 SKILL 正文约束"按类别只读对应 references 文件"
- 存档写入 → 模型直接 `write`，由 P5 的快照兜底
- 不再保留 `plan_panel_update` 一类的 gate 工具

**验收**：常规回合端到端可玩；坏写入可回滚。
**依赖**：P5。

### P7 · battle

**暂缓**——流程本身未完成，等 game 跑通且 battle 设计定稿后再做。

---

## 5. 迁移策略：并行运行，逐流程切换

不要一次性替换。新旧路径并存，用开关逐步切换：

1. Flask 保留现有 `System/consult`、`System/game` 代码路径
2. 新增 DSH 路径，按用户/存档（或全局开关）选择走哪条
3. **先切 consult**（最独立、最简单）
4. 稳定后再切 game 常规回合
5. battle 不动

好处：**每个流程都能独立回退**，且回退不需要 revert 代码——切回开关即可。

配合已有的备份基点（`main` @ `00cbb7f`），最坏情况是丢掉全部改动——但按上面的顺序不会走到那一步。

---

## 6. 暂缓项

| 项 | 状态 | 恢复时的注意 |
|---|---|---|
| **中英双语** | 暂缓 | 先跑通中文。**结构上必须隔离**：`consult-zh/` 与 `consult-en/` 是两份独立文件，**不要在一个 SKILL.md 里做语言分支**——那会导致"改一份要改两处"。现有 `game_zh.py` / `game_en.py` 已是这个模式，照搬 |
| **battle** | 暂缓 | 流程未完成 |

---

## 7. 不可违反的约束

1. **工具面最小**：不挂 bash / subagent / workflow / web。这是读围栏得以完备的前提——有 shell 就能 `cat` 任何东西
2. **快照在模型写围栏之外**：否则等于没做
3. **`.env` / `account.db` 不在 DSH 可达范围内**：`FLASK_SECRET_KEY` 泄露 = 可伪造任意用户 session = 全站接管
4. **RAG adapter 与 RAG 同 repo 同 commit**：避免版本漂移

---

## 8. 尚未验证的假设（P0 要回答的）

- [ ] DSH 的 `session.event` 能拿到逐 token 的 thinking
- [ ] 思考/正文/工具调用能映射到前端现有的事件类型
- [ ] 模型在只读/写 + skill 的工具面下，能可靠地走完三段流程
- [ ] 无 approver 时沙箱提权确实 fail-closed
