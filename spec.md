# LetsPlayDnD × DSH 迁移 Spec

---

## 1. 概述

将 LetsPlayDnD 的 agent 编排从手写 Python 流程迁移到 DeepSeek Harness（DSH）。前端与账号体系保持不变，通过事件适配层对接。

DSH 与 Flask 之间的通道采用社区插件 `dsh2server`：DSH 实例**主动连出**到 Flask，上行推送实时事件（含逐 token 流），下行接受会话操作。协议有完整文档与两份参考实现，Flask 侧按文档实现服务端即可。

---

## 2. 范围

### 2.1 目标

| 现状 | 目标 |
|---|---|
| `System/consult`、`System/game` 中的固定 DAG | SKILL.md 描述的流程，由模型推进 |
| `Prompts/*.md` 按 stage 加载 | SKILL.md 正文 + `references/` 资源 |
| 19 个 function-calling 工具 | `read` / `write` / `edit` / `skill` + 2 个 MCP 工具 |
| Python 手写工具分发 | DSH 工具分派 |
| 自定义单进程 LLM 调用 | 每用户一个 DSH 实例 |

### 2.2 范围外

| 项 | 说明 |
|---|---|
| battle 流程 | 流程本身尚未完成，暂缓 |
| 中英双语 | 暂缓；当前仅实现中文 |
| DSH 插件**开发** | 不编写任何 DSH 插件；仅**安装并使用**第三方 `dsh2server` |

---

## 3. 目标架构

```
浏览器 (UI/)
   │  SSE（前端不变更）
   ▼
Flask ── 前端接口 / 账号 / 存档元数据 / 中转服务器
   │
   ├──▶ account.db
   └──▶ Account/<user>/Saves/<id>/

   ▲  WebSocket（DSH 主动连出，非 Flask 主动连接）
   │
DSH 实例（每用户一个，web-capable profile）
   ├── dsh2server 插件 ── 事件上行 / 操作下行
   └── MCP over HTTP
          │
          ▼
      MCP 服务（常驻单进程）── import ──▶ RAG/ + Dice/
```

**连接方向**：由 DSH 主动连出。Flask 不需要访问实例所在主机，实例也不需要开放入站端口。

---

## 4. 部署拓扑

### 4.1 仓库布局

单仓库，服务器通过 `git pull` 更新。

```
/opt/letsplaydnd/
  server.py
  System/
  UI/
  RAG/
  Dice/
  Skills/
    consult/
      SKILL.md
      references/
  MCP/
    mcp_server.py
  Relay/                    # dsh2server 协议的服务端实现
  dsh/
    profile.patch.yml
    units/

/var/lib/letsplaydnd/history/         # 存档快照裸库（工作区之外）
/var/lib/letsplaydnd/users/<name>/    # 每用户 DSH_HOME（0700）
```

### 4.2 组件职责

| 组件 | 职责 | 部署单元 |
|---|---|---|
| Flask | 前端接口、账号、存档元数据 | `server.py` |
| 中转服务器 | dsh2server 协议服务端；实例注册、事件接收、操作下发 | `Relay/`，与 Flask 同进程或独立进程 |
| MCP 服务 | 提供 `search_rules`、`roll_dice` | 独立常驻进程 |
| DSH 实例 | agent 循环、skill 加载、工具分派 | 每用户一个 |
| `dsh2server` | DSH 侧桥接：上行事件、下行操作 | DSH 插件 |
| 存档快照 | 回合级版本化与回滚 | 工作区外裸库 |

### 4.3 配置分发

每用户拥有独立 `DSH_HOME`。与用户无关的配置通过 patch 文件注入：

```bash
dsh --profile <name> --patch /opt/letsplaydnd/dsh/profile.patch.yml
```

patch 内容：`customSkillDirs`、工具 allowlist、MCP 服务地址、模型路由、`dsh2server` 的 endpoint。
用户私有内容（凭据、`DSH_HOME` 路径）通过环境变量传入。

`dsh2server` 的 endpoint 也可由环境变量 `DSH2SERVER_ENDPOINT` 提供。

### 4.4 更新与重启矩阵

| 变更对象 | 需重启 DSH | 机制 |
|---|---|---|
| Skill 正文 | 否 | 每次加载重新读取文件 |
| Skill frontmatter | 否 | 下一模型步骤刷新目录 |
| `references/` 资源 | 否 | 模型按需读取，无缓存 |
| MCP 服务代码 | 否 | 客户端自动重连并刷新工具集 |
| profile patch | 否 | 自定义 profile 默认 `patchReload: live` |
| `dsh2server` 的 endpoint | 否 | 该插件 GUI 配置立即生效 |
| 其余 `dsh2server` 配置 | 否 | 同上 |
| 插件包增删 | 是 | bundle 名单变化 |
| DSH 本体升级 | 是 | — |

**MCP 重试预算**：`reconnect.maxAttempts` 默认 10，延迟自 500 ms 起翻倍、上限 30 s，累计约 2.5 分钟。超出后该服务的工具被移除且停止重连，需重载配置或重启 harness。

**中转服务器不可达时**：`dsh2server` 按同样策略退避重连（默认 1 s 起、上限 60 s）。服务器补登 key 或恢复后，实例会自动恢复，无需重启 DSH。

---

## 5. 组件规格

### 5.1 MCP 服务

| 项 | 规格 |
|---|---|
| 实现 | Python，直接 import 现有 `RAG/` 与 `Dice/` |
| 传输 | Streamable HTTP，监听 127.0.0.1 |
| 生命周期 | 常驻单进程，由 systemd 管理 |
| 工具 `search_rules` | 参数 `query`、`context_label`；调用 `RAG/` |
| 工具 `roll_dice` | 参数 `names`、`dice_type`、`nums`、`sides`；调用 `Dice/` |

**传输选型**：stdio 由每个 DSH 实例各自 spawn 服务进程，将导致 N 份 Chroma 与 embedding 模型常驻内存。HTTP 由全部实例共享一份。

**版本一致性**：adapter 与 RAG 实现处于同一仓库、同一次提交，不存在独立版本。

### 5.2 Skills

**位置**：`Skills/<name>/`，与项目并列存放。当前为 `Skills/consult/`。

**结构**：

```
Skills/
  consult/
    SKILL.md            流程总纲
    references/         各阶段指令，按需读取
      decision.md
      rag-query.md
      output.md
  game/                 与 consult 并列（P6）
    SKILL.md
    references/
```

**约束**：

- 目录式 bundle：被扫描的根下直接是 `<name>/SKILL.md`；**不支持嵌套** `**/SKILL.md`
- frontmatter 必填 `name`（kebab-case，且与目录同名）与 `description`；可选 `whenToUse`、`disable-model-invocation`、`user-invocable`
- **`references/` 下的文件不会自动进入上下文。** skill 工具返回 `<skill_resources>` 块，给出该 skill 的**绝对基目录**并要求按基目录解析相对路径；模型须自行用 `read` 读取。因此 SKILL.md 正文必须显式写明要读哪些文件
- 语言隔离：中文与英文为独立目录，不在同一 `SKILL.md` 内做语言分支。当前仅有 `consult/`；引入英文时再定命名（见 §2.2 暂缓项）

### 5.3 DSH profile

必须是 **web-capable** profile：`dsh2server` 的会话能力来自 `sessionController`（由 web 组合提供）。不能使用 `sdk` / `sdk-minimal`。

**挂载**：

| 包 | 用途 |
|---|---|
| `dsh-web-app`（或等价组合） | 提供 `sessionController` 等会话服务 |
| `dsh-tool-fs` | `read` / `write` / `edit` |
| `dsh-tool-skill`、`dsh-skill`、`dsh-skill-filesystem` | skill 目录与加载 |
| `dsh-fs-sandbox`、`dsh-sandbox-policy` | 写入围栏 |
| `dsh-fs-observation-policy` | 读后写策略 |
| `dsh-mcp-client` | MCP 桥接 |
| `dsh2server` | 与 Flask 的桥接 |

**不挂载**：`dsh-tool-bash`、`dsh-tool-pwsh`、`dsh-tool-jobs`、`dsh-tool-fs-search`、`dsh-tool-subagent`、`dsh-tool-subagent-control`、`dsh-tool-workflow`、`dsh-tool-todo`、`dsh-tool-goal`、`dsh-tool-ralph`、`dsh-tool-web`。

> ⚠️ `skill-filesystem` 与 `tool-skill` 两行在 web 组合下**默认被禁用**（该组合让 agent preset 接管本地 skill 发现）。要用 `customSkillDirs` 指向项目 `Skills/`，必须显式重新启用 host 行或改配 preset——机制与做法见 §6 P3。

**沙箱配置**：`mode: workspace-write`，`workspaceRoot` 指向当前存档目录。

**需单独安装的包**：`dsh-mcp-client`（不在 `dsh-base` 中）。

```bash
dsh plugin --profile <name> add @deepseek-ai/dsh-mcp-client
dsh plugin --profile <name> add github:23J1633/dsh2server
```

### 5.4 中转服务器（Flask 侧）

实现 `dsh2server` 协议 v1 的**服务端**。规范见该插件的 `docs/API.md`。

| 项 | 规格 |
|---|---|
| 端点 | `{basePath}/ws`（WebSocket 升级）、`{basePath}/events`（POST）、`{basePath}/inbox`（GET） |
| 传输 | 优先 WebSocket；HTTP 长轮询为回退 |
| 认证 | `hello` 帧的 `auth.key`，或 `Authorization: Bearer`，或 `?key=` |
| 实例模型 | 一 key 一实例；key 恒定时间比较；持久化白名单 |
| 上行 | `session/event`、`session/status`、`session/activity`、`session/assistant-stream` |
| 下行 | `session.prompt`、`session.interrupt`、`session.pause`/`resume`、`session.create`、`session.list`、`session.history`、`session.permission`、`approval.respond` 等 |
| 序号 | 按 `seq` 去重；`hello.resumeFromSeq` / `hello.ack.resumeFromSeq` 实现补发 |

**必做清单**（规范 §12）：端点、key 白名单、认证、`hello → hello.ack`、`subscribe`、请求/响应配对与超时、事件按 `seq` 去重、心跳、HTTP 载体的 per-instance 待发队列、`bye` 处理、多机器隔离。

**参考实现**：插件包内 `examples/server.js`（Node，WebSocket + HTTP）与 `php/dsh-relay.php`（PHP 单文件，HTTP 长轮询）。后者是最贴近 Flask 的移植起点。

### 5.5 前端事件映射

`dsh2server` 的 `session/assistant-stream` 帧与前端现有事件类型几乎一一对应：

| 帧 | 前端事件 |
|---|---|
| `frame.type = start` | 新气泡开始 |
| `chunk.chunk.type = reasoning-delta` | `thinking` |
| `chunk.chunk.type = text-delta` | `content` |
| `chunk.chunk.type = block-start` / `block-end` | 内容块边界 |
| `chunk.chunk.type = finish` | `done` |
| `frame.type = end` | 气泡结束 |

前端**不需要改动**事件模型，只需在中转服务器侧写翻译层。

---

## 6. 实施阶段

**阶段总览**（依赖关系与编号顺序不完全一致：P4 先于 P3 完成）：

| 阶段 | 内容 | 依赖 | 状态 |
|---|---|---|---|
| P0 | 技术验证 | — | ✅ 已完成 |
| P1 | MCP 服务 | — | ✅ 已完成 |
| P2 | consult skills | P1 | ✅ 已完成 |
| P3 | DSH profile | P1、P2 | ✅ 已完成（§9 三条验证移交 P6） |
| **P3.5** | **consult 适配层**（新增） |  P2、P3、P4 | ✅ 已完成 |
| P4 | 中转服务器 | — | ✅ 已完成 |
| P5 | 安全加固 | P3.5 | 进行中（key 白名单、存档快照、读白名单 已完成；剩回环租户隔离） |
| P6 | game 流程迁移 | P5 | 待做 |
| P7 | battle | — | 暂缓 |

### P0 技术验证 —— 已完成

**内容**：以独立 `DSH_HOME` 启动 SDK profile，通过 Python SDK 提交提示词，记录 `session.event` 输出。

**结论**：

| 项 | 结果 |
|---|---|
| 逐 token 流（SDK `session.event`） | ❌ 不可用。全部事件在 step 结束时一次性到达；4 秒生成期间零事件 |
| 逐 token 流（ACP） | ❌ 规范明确排除"原始提供方增量" |
| 逐 token 流（`dsh2server`） | ✅ 可用。实测 486 帧 / 2.26 秒，帧间隔中位 10 ms，含 370 `reasoning-delta` + 108 `text-delta` |
| `dsh2server` 能力覆盖 | ✅ 除 `terminal` 外全部可用 |

**由此确定**：桥接通道采用 `dsh2server`，SDK 仅用于未来可能的自动化脚本。

**遗留**：P0 的验收项「模型在极简工具面下完成三段流程」依赖 P3，移至 P3 验收。

### P1 MCP 服务 —— 已完成

**内容**：实现 `MCP/mcp_server.py`（两个工具）与 systemd 单元。

**验收**：两个工具可经 MCP 调用；进程常驻；RAG 仅加载一次。

**依赖**：无。

**结果**：

| 项 | 结果 |
|---|---|
| 工具 schema | 与原 `Tools/consult/rag_tools_zh.py`、`Tools/dice/dice_tool_zh.py` 的定义完全一致 |
| `roll_dice` 输出格式 | 与原执行逻辑逐字一致（`骰子使用者：…，类型：…，数量和面数：NdM，结果：[…]`） |
| `search_rules` 输出格式 | 含 `[context_label]` 前缀，与原逻辑一致；返回真实规则内容 |
| **RAG 仅加载一次** | 首次调用 10.2 s（加载 embedding 模型），第二次 **0.2 s** |
| 服务 | Streamable HTTP，监听 `127.0.0.1:8790`，路径 `/mcp` |

**实现要点**：

- `mcp` 2.x 将 `FastMCP` 更名为 `MCPServer`（`mcp.server.mcpserver`），Streamable HTTP 用 `streamable_http_app()` + uvicorn
- `RAG` 在工具函数内惰性 import：进程启动轻量，模型在首次调用时载入并常驻
- 产物：`MCP/mcp_server.py`、`dsh/units/letsplaydnd-mcp.service`

**遗留**：

- systemd 单元需在目标 Linux 主机上用 `systemd-analyze verify` 复核
- 常驻内存未实测（本机 `ps` 被沙箱禁用）；建议在服务器上用 `systemd-cgtop` 确认，该数值决定「N 个 DSH 实例共享一份 MCP」的收益

### P2 consult skills —— 已完成

**内容**：编写 `Skills/consult/`，迁移 `Prompts/consult/` 内容至 `references/`。

**依赖**：P1。

**结果**：

```
Skills/consult/
  SKILL.md              流程总纲（原 agent 的编排）
  references/
    decision.md         判断是否需要检索
    rag-query.md        关键词改写后调用 search_rules
    output.md           输出与规则引用
```

`Skills/rag-query/` 已删除（内容并入 `references/rag-query.md`）；`Prompts/consult/` 按清理策略保留（见 §7）。

| 项 | 结果 |
|---|---|
| 结构校验 | ✅ frontmatter 合法、`name` 为 kebab-case 且与目录同名、无嵌套 `SKILL.md` |
| 可被发现 | ✅ `consult` 出现在会话的 skill 目录中 |
| 热加载 | ✅ 修改 skill 无需重启 |
| **references 可读** | ✅ skill 工具返回 `<skill_resources>` 块，给出**绝对基目录**并要求按基目录解析相对路径；实测可读 |

**要点**：`references/` 下的文件**不会自动进入上下文**，SKILL.md 必须显式要求模型用 `read` 读取。此点已实测确认。

**待补**：完整「判断 → 检索 → 输出」链路需 `search_rules` 工具可用，属 P3 验收。

### P3 DSH profile

**内容**：编写 `dsh/profile.patch.yml`，基于 web-capable profile，包含四项：

1. **工具面裁剪** —— 只挂 `dsh-tool-fs`、`dsh-tool-skill`、沙箱相关与 `dsh-mcp-client`；不挂 shell / subagent / workflow / web 等
2. **skill 发现** —— 配置 `customSkillDirs` 指向 `Skills/`
3. **MCP 工具** —— 安装并配置 `dsh-mcp-client` 指向 P1 的服务
4. **`dsh2server`** —— 与 Flask 的桥接

#### ⚠️ skill 发现的关键机制（P2 实测发现）

web profile **禁用了 host 层的 `skill-filesystem` 与 `tool-skill`**：

> `@deepseek-ai/dsh-web-app/cordis.patch.yml`：the base host `skill-filesystem` row is disabled here (**presets own local discovery**) … `tool-skill` is what a preset mounts to give its agent the catalog and loader at all.

skill 注册表是 **host + per-scope 分层**的：host 行注册进 global 层，preset 行注册进该 preset 层，agent 读到的是沿 scope 链合并后的目录。

因此有两种做法：

| 做法 | 说明 |
|---|---|
| **A** 重新启用 host 行 | patch 中写 `- id: skill-filesystem` + `disabled: false` + `customSkillDirs`；注册进 global 层，全部 preset 共享 |
| **B** 配置 agent preset | 在 preset 内挂 `skill-filesystem` 与 `tool-skill`；每个 preset 可有各自的 skill 集 |

本地验证用的是 A（改 `~/.dsh/profiles/web/cordis.patch.yml`）。生产应随 profile / preset 一并固化。

#### 验收

- 模型可见工具恰为 `read` / `write` / `edit` / `skill` / `mcp__*`
- 工作区外写入返回拒绝
- 沙箱模式不可由模型自行提升
- `search_rules` 与 `roll_dice` 可被模型调用
- **模型完成一次完整的三段流程（判断 → 检索 → 输出），规则引用正确**
- skill 目录中只出现预期 skill

**依赖**：P1、P2。

**结果 —— 已实现并本地验证**

产物：

```
dsh/
  profile.patch.yml                              profile 覆盖层
  agent-presets/letsplaydnd/
    preset.yml                                   名单元数据
    agent.cordis.yml                             ★ 工具面真正定义在这里
  units/letsplaydnd-mcp.service
```

`profile.patch.yml` 负责三件事：把 preset 目录挂进 roster 并设为部署默认、插入 MCP 行、设沙箱模式。

| 验证项 | 结果 |
|---|---|
| preset 被发现 | ✅ 出现在 preset 名单中 |
| **工具面裁剪** | ✅ 模型自报可用工具恰为 `read` / `write` / `edit` / `read_image` / `skill`——无 shell、无 web、无 subagent、无 workflow、无 todo/goal |
| preset 挂载（含压缩组） | ✅ 正常运行，无错误 |
| MCP 工具 | ✅ 随 P3.5 consult 端到端实测通过：模型成功调用 `search_rules`（并据召回结果正确声明"非规则书引用"） |
| 沙箱 `workspace-write` | ✅ 同上（模型写入存档成功，工作区外写入被拒） |
| skill 目录 | ✅ 只出现预期 skill（`consult`） |
| **三段流程** | ✅ consult 端到端实测通过（判断 → 检索 → 输出），浏览器内验证：流式正文、思考过程、持久化、单气泡渲染均正常 |

> 上表最后四行原先标为"待 `--patch` 重启后验证"，实际已由 P3.5 的 consult 端到端实测覆盖，故订正。
> 剩余未做的只有 §9 的三条**边界**验证（无 approver 时的提权失败关闭、极简工具面下的稳定性、
> `dsh2server` 能力集合），它们更适合在 P6 的完整游戏流程里做，已移交 P6。

#### ⚠️ 五个实现坑（都已踩过）

1. **工具面由 agent preset 决定，不是 profile patch。**
   web 组合把 host 平面的工具行**全部禁用**，改由 preset 提供。因此在 patch 里写 `disabled: true` 是 no-op——第一版 patch 就犯了这错。真正要改的是 `agent.cordis.yml`。

2. **preset 发现不跟随符号链接。**
   在 `~/.dsh/.agent-presets/` 放 symlink 不会被识别；必须是实体目录。（配置 `roots` 指向项目目录时不受影响。）

3. **`@deepseek-ai/dsh-mcp-client` 的两个坑。**
   一是不声明 `dsh.bundle`，装它是普通依赖，靠 `insert` 行激活；二是**必须钉版本**——`pnpm add @deepseek-ai/dsh-mcp-client` 会拉到陈旧的 `0.0.1-rc.1`，而 `dsh` 自带的是 `0.1.5-rc.2`：

   ```bash
   dsh plugin --profile <name> add '@deepseek-ai/dsh-mcp-client@0.1.5-rc.2'
   ```

4. **⚠️ 会话运行期间不要改 profile patch。**
   profile 是 `patchReload: live`，编辑它会触发实时重组；**重组会脱挂正在运行会话的 agent 平面**——host 平面的注册（MCP 工具等）还在，agent 平面的工具（`read` / `write` / `bash`）全部消失，会话随即不可用。改完必须重启 DSH。
   （实测复现两次：编辑 patch → 工具全部 `unknown tool`，而 MCP 工具仍可调用。）

5. **⚠️ roster 的 `default` 不能省略。**
   把 `agent-presets` 的 `default` 去掉会让 DSH **直接无法启动**。该字段必须给一个存在的 preset id。

**注意**：bundle 变更**需要重启** DSH。

#### `default` 的取值

`default` 决定**所有新建会话**的 preset，包括用来开发的 GUI 会话。因此**不要**把它设成本项目的极简 preset——那会波及开发会话，让它们失去 shell 等工具。

极简 preset 由 **P3.5 的适配层在创建游戏/咨询会话时显式选择**（`agentPreset.select`），部署默认仍是 `standard`。

#### 上下文压缩不能省

preset 里挂了 `compaction` 组（`compaction-basic` + `command-compact` + `tool-result-pruner`）。
它不是模型可见的工具，所以不违反「最小工具面」；但不挂它，上下文会随回合无限增长，
最终模型调用直接失败——旧系统是靠 `history[-20:]` 手动截断回避这个问题的。

---

### P3.5 consult 适配层（新增）

**来源**：P2 完成后发现，原 P0–P7 遗漏了这一环——前端调用的是 `/api/consult/message/stream`，而 DSH 流式端点是 `/api/dsh/stream`，两者之间没有连接。

**目标**：让**前端零改动**地走 DSH。做法不是改前端，而是让 `/api/consult/message/stream` 内部改走 DSH。

**内容**：

1. **会话映射** —— 维护 (用户名, 存档) → DSH 会话 id 的对应关系；首次访问时创建 DSH 会话并落库。存放位置：`account.db`（可与 `dsh_instances` 同库另建表）
2. **兼容端点** —— `POST /api/consult/message/stream` 在 DSH 开关打开时：
   - 由 `relay_state.instance_for_user()` 解析该用户的实例（无则拒绝）
   - 解析或创建对应的 DSH 会话
   - 订阅该会话并下发提示词
   - 用 `Relay/sse.py` 的 `iter_frontend()` 产出前端既有事件格式
3. **开关** —— 新旧路径并存，按用户或全局开关切换（见 §7）

**验收**：

- **前端一行未改**，consult 在浏览器中可正常提问、流式出字、显示思考
- 规则类问题能触发 `search_rules` 并引用规则书原文
- 输出事件与旧路径一致（`thinking` / `content` / `new_bubble` / `end_bubble` / `done`）
- 用户未绑定 DSH 实例时明确报错，而不是静默失败

**依赖**：P2、P3、P4。

**这是「`python server.py` 之后就能在前端测 consult」的分界线**——此阶段完成后才成立。

#### 结果 —— 已实现并端到端验证

产物：`Relay/adapter.py`（会话映射 + 流式适配），`server.py` 加开关 `DSH_CONSULT_ENABLED`。

| 项 | 结果 |
|---|---|
| 前端改动 | **0 行** |
| 会话映射 | `account.db` 的 `dsh_sessions` 表，(用户名, 存档) → DSH 会话 id |
| preset 选择 | 建会话时**显式** `agentPreset.select → letsplaydnd`，不依赖部署 `default` |
| 流式输出 | 一次实测 761 条事件（`new_bubble` ×5、`thinking` ×233、`content` ×517、`done` ×1），11 秒 |
| **技能流程** | ✅ 会话日志确认：技能目录含 `consult` → 调用 `skill` ×1 → `read` ×3（三个 references）→ `search_rules` ×3 |
| 查询改写 | ✅ 模型给出 `火球术 豁免 伤害`，完全符合 `rag-query.md` 的要求 |
| 落库 | ✅ user + assistant（含 reasoning）写入 `chat.db`，刷新页面历史仍在 |
| 输出纪律 | ✅ 未命中时按 `output.md` 明确声明"不是规则书直接引用，可能有误" |

**唯一未达标项**：验收里的「引用规则书原文」——原因是 **RAG 召回质量**，非迁移问题，见 §10.3。

#### ⚠️ 附带发现的坑：不能按 step 发气泡边界

DSH 的一个回合可能包含多个 step（模型 → 工具 → 模型），每个 step 都有自己的 `start`/`end`。v1 把 `start` → `new_bubble`、`end` → `end_bubble`，结果前端把一轮切成了多个 DM 气泡：某步只有思考没有正文时，就出现「一个只有思考的气泡 + 一个只有正文的气泡」。

而落库的是**整条** assistant 消息，所以**刷新后又变回正确的单气泡**——生成过程与刷新后呈现不一致，正是这个原因。

修法：**不发气泡边界**，思考与正文都按整轮累计。前端 `thinking`/`content` 分支各自会 `openBubbleForWrite()`，不需要边界事件开气泡；整轮共用一个，由 `done` 收尾。这样流式呈现与刷新后的历史完全一致。

> **边界机制保留待用**：battle 里 DM 可能一口气推进多个回合、需要拆成多个气泡。届时把 `frame.type == "start"/"end"` 重新映射到 `new_bubble`/`end_bubble` 即可。但在那之前要先定清楚"一个气泡"对应 DSH 的什么单位——是 step，还是别的边界。正常非战斗流程应始终保持整轮一个气泡。

#### ⚠️ 附带发现的坑：重启 Flask 后的首次请求必失败

中转的实例表在**内存**里，Flask 一重启就空了；插件要按退避重连（最长 60 秒）。这段空窗里 `instance_for_user()` 返回 None——原本直接报 `no dsh instance bound to this account`，用户看到的就是「刚重启后第一次提问必然失败，刷新一下又好了」。

修法：`wait_for_instance()` 做**有界等待**（默认 45s，可配），把这段窗口吸收掉；真超时才给明确的中文提示。

> 更根本的做法是让实例表可跨进程重启（持久化或独立进程），但那超出当前阶段。

#### ⚠️ 附带发现的坑：SSE 不能发 `id:` 行

`Relay/sse.py` 原本按 SSE 标准发 `id: <seq>` 以便前端做断线续传。但前端解析器（`UI/js/chat-view.js`）是这样判块的：

```js
const parts = buffer.split('\n\n');
for (const part of parts) {
  const line = part.trim();
  if (!line.startsWith('data:')) continue;   // ← 整块必须以 data: 开头
  const ev = JSON.parse(line.slice(5).trim());
```

块里一旦有 `id:` 行，`line` 就变成 `"id: 1\ndata: {...}"`，`startsWith('data:')` 为假——**每一条事件都被静默丢弃**。

症状很有迷惑性：**服务端执行成功、也已落库（刷新页面能看到完整回复），但前端一个字都不渲染，加载动画消失后什么都没有。**

修法：只发 `data:` 行，把序号放进 JSON 载荷的 `seq` 字段。现有前端会忽略它，将来要续传时直接读，两边都不必改协议。

> 教训：给已有前端新增 SSE 字段前，先读它的解析器。前端可能不是标准 SSE 客户端。

#### ⚠️ 附带发现的坑：`customSkillDirs` 的生产路径回退

preset 里原本写的是：

```yaml
- !!js process.env.DSH_SKILLS_DIR ?? '/opt/letsplaydnd/Skills'
```

本地没设 `DSH_SKILLS_DIR`，于是回退到**生产路径**——本地不存在，扫不到任何 skill。后果很隐蔽：**技能目录不下发，模型根本不知道 `consult` 存在**，于是跳过技能直接乱查。

已改为 `process.cwd() + '/Skills'`：生产与本地的启动命令都是 `cd <项目根> && dsh ...`，两边都成立。

### P4 中转服务器 —— 已完成

**内容**：在 Flask 侧实现 `dsh2server` 协议 v1 服务端，覆盖规范 §12 的必做清单。

**范围界定**（对照 `php/dsh-relay.php`，全文 1600 行）：

| 部分 | 行数 | 是否移植 |
|---|---|---|
| 配置 / 基础工具 / key 白名单 | 37–176 | 是（多数由 Flask 内置替代） |
| 状态存取 | 177–315 | **否**。实例状态改为内存，key 白名单复用 `account.db` |
| 核心协议路由 | 316–561 | 是，主体 |
| 管理接口 | 562–808 | 部分是 |
| HTML 调试台 | 809–1600 | **否** |

协议允许服务器无状态："服务器进程重启后，所有 dsh 会自动重连并重新推送状态"。

**路由**：

| 路由 | 说明 |
|---|---|
| `POST {base}/events` | 插件上行：`hello` / `event` / `response` / `ping` / `ack` / `bye` |
| `GET {base}/inbox` | 插件下行：长轮询 |
| `GET/POST {base}/keys`、`POST {base}/keys/remove` | key 白名单 |
| `GET {base}/instances` | 实例表 |
| `GET {base}/instances/:id/events` | 事件窗口 |
| `POST {base}/instances/:id/request` | 下发操作 |
| `POST {base}/instances/:id/subscribe` | 订阅 |

不移植 `/pending*`（配对流程，两端均本项目控制）与 `/admin/clear`。

**传输选型**：先只实现 **HTTP 长轮询**（`/events` + `/inbox`）。协议中两种载体等价，插件在 `transport: auto` 下自动回退。不引入 WebSocket 依赖。`GET {base}/ws` 返回 426 明示不支持。

**模块布局**：

```
Relay/
  __init__.py
  protocol.py     帧类型与帮助函数
  state.py        RelayState：实例表、事件环、inbox 队列、key 白名单
  blueprint.py    Flask Blueprint：核心协议 + 管理接口
  devserver.py    独立运行入口，用于验收
```

**预计规模**：约 350 行 Python，纯标准库。

**约束与注意事项**：

1. **必须单进程**。实例状态在内存中；多 worker 会使同一实例被分散到不同 worker。key 白名单除外，它在 `account.db`。
2. **长轮询占用 worker**。Flask 须以 `threaded=True` 运行，否则单个长轮询阻塞整个服务。实例数增长后需考虑异步 worker。
3. **密钥比较使用 `hmac.compare_digest`**（规范要求恒定时间比较）。
4. **每实例维护事件环形缓冲**，按 `seq` 去重；重连时依 `hello.ack.resumeFromSeq` 补发；缓冲不足时发送 `bridge/resync`。
5. **`bye` 标记为断开而非删除**（规范：紧接其后的重连会与删除抢跑）。

**验收**：

- 一个 DSH 实例能连接并出现在实例表中
- `session/assistant-stream` 的 `reasoning-delta` 与 `text-delta` 能实时转发到前端
- 下发 `session.prompt` 能驱动会话并收到完整回复
- 断线后能自动重连并按 `seq` 补发，不丢事件
- **前端 SSE 支持按 `seq` 续传**：浏览器断线重连后能补回缺失片段，不丢内容

**依赖**：P3。

**起点**：移植 `php/dsh-relay.php`，对照 `examples/server.js`。

**结果**：

Flask 侧实现见 `Relay/`（1090 行），已接入 `server.py`（Blueprint 注册于 `/dsh-api`），并在真实 DSH 实例上端到端验证：

| 项 | 结果 |
|---|---|
| 前端事件产出 | 179 条（`new_bubble` ×1、`thinking` ×138、`content` ×38、`end_bubble` ×1、`done` ×1） |
| `done.content` 与增量拼接 | 一致 |
| SSE 序号 | 放在 JSON 载荷的 `seq` 字段。**不发 SSE 标准的 `id:` 行**——前端解析器按「整块是否以 `data:` 开头」判断，块里出现 `id:` 会被整条丢弃（详见 P3.5 结果里的坑） |
| key 白名单 | 落 `account.db` 的 `dsh_instances` 表；`username` 承载归属 |
| 鉴权 | 未登录 401、缺 `sessionId` 400、未绑定实例 403（fail closed） |
| 断线恢复 | 插件在 relay 重启后自动重连 |
| 路由共存 | `/dsh-api/*` 未被 `/<path:filename>` 兜底抢占 |

**遗留**：

- 前端尚未消费 `id:`；续传需前端配合（记录 `lastSeq` 重连，或改用 `EventSource`）
- 每用户实例的自动创建与端口分配待 P3 落地后补；当前实例由管理员手工登记在 `dsh_instances`

### P5 安全加固

**内容**：

1. **模型文件读取白名单**（`ctx.fs` 工具层）— 见 P5-1，**已完成并端到端验收**
2. 存档快照（工作区外裸库）— **已完成**（`Relay/snapshot.py`）
3. 中转服务器的 key 白名单与恒时比较 — **已完成**（P4）
4. 回环租户隔离（多实例部署时）
5. ~~每用户 DSH 实例的 systemd 文件系统命名空间隔离~~ — **降级为暂缓**，理由见 P5-1「为什么不选 systemd」

**验收**：模型经 `read` / `read_image` 无法读取 `.env`、`account.db` 及白名单外的任何路径；
DSH 进程自身不受影响（仍能正常启动与运行）；存档可回滚至任意回合。

#### P5-1 模型文件读取白名单

**威胁模型**（边界先说清，因为它决定方案的形态）

- **挡**：模型被提示注入误导——游戏内容或玩家输入里夹带指令，诱导它去读密钥、再念出来。模型没有 shell、没有网络，泄露渠道只有自己的文本输出、写入存档、以及 MCP 工具参数。
- **不挡**：攻击者在 DSH 进程内取得代码执行（例如 DSH 自身的漏洞）。那种情况下只有容器 / 微虚拟机有用，与本设计无关。
- **前提**：**预设内不存在不可信代码**。见下方不变量。

**为什么是白名单而不是黑名单**

实现成本完全相同——同一个检查点、同一段代码，只是比较方向反过来。所以只需比较失败模式：

| | 失败模式 |
|---|---|
| 黑名单 | 出现新的秘密文件而未被列入 → **静默 + 灾难**。且要求穷举"现在和未来所有秘密"，不可能做到 |
| 白名单 | 模型读不到某个正当文件 → **吵闹 + 无害**（模型会报告读不到，加一个根即可） |

白名单只需枚举**我们自己的**目录，不需要枚举秘密。这是选它的唯一理由，也是最充分的理由。

**根表**

| 根 | 读 | 写 | 依据 |
|---|---|---|---|
| `ROOT/Account/<username>` | ✅ | ✅ | 就是当前的会话 cwd（`server.py:829`），**天然的用户级边界** |
| `Skills/` | ✅ | ❌ | **必需，不能漏**：`Skills/consult/SKILL.md:9-10` 要求模型"用 read 工具读取对应文件"，不给它读 consult 直接跑不动 |
| `Templates/` | ❌ | ❌ | **暂不列入**（未列入白名单即不可读）。模板是「开局」阶段由 Flask 侧复制成存档，模型没有读写必要。以后可能需要只读（例如游戏自建人物时参考格式），届时再加 |

只有两个根。未列入的路径**默认不可读也不可写**——这正是白名单的意义，不需要为 `Templates/` 写任何"禁止"规则。

注意读写根**故意不同**：`Skills/` 必须可读但不可写，否则模型能改自己的指令。
本项是在现有 `workspace-write`（只管写、根 = 会话 cwd）**之上补一条读规则**，不替换它。

**不变量**（是白名单的成立条件，不是附加项）

> 本预设不得引入任何可执行代码的工具（bash / pwsh / 带 shell 的 subagent / 等价物）。
> 引入即等于同时拆除读白名单。

理由：白名单是**可信代码中的策略**，只在"模型只能发工具调用、没有第二条通往文件系统的路"时完备。
DSH `dsh-fs-sandbox` README 的原话：围栏是策略而非内核边界，**只有目标路径不可信**，
因此「规范化后检查包含关系」就是该接口的完整答案；不可信代码的内核级隔离由 `ctx.shell` 负责。
当前预设工具面 = `tool-fs`（`read`/`read_image`/`write`/`edit`）+ `skill-filesystem` + `tool-skill`，
没有 bash、web、subagent、`tool-fs-search`；MCP 工具运行在我们的进程里，不是文件系统通道。**前提成立。**

**落地方式 —— 已实现**（`dsh/plugins/fs-readguard/`）

选 `ctx.tools.guard()`，**不是** fs 后端，也不是 `tools/pre-execute`：

- guard 是**单调**的：跑在可扩展的 pre-execute waterfall 之后，只能拒绝、不能放行，
  所以监听器顺序无法把拒绝翻回允许。用在安全控制上这是正确语义。
- 不动 `ctx.fs` 后端的装配（不替换 `fs-sandbox`），改动面小、可逆，摘掉插件即回到原状态。

实现要点：

| 决定 | 理由 |
|---|---|
| 只拦 `read` / `read_image` | 写围栏已由 `sandbox-policy` 负责（可写根 = 会话 cwd）且带升权提示；再拦一次会让同一件事出现两套冲突报错 |
| 根从 `agent.session.header.cwd` 取 | 与 `dsh-tool-fs` 取 cwd 的方式一致。**不能退回 `process.cwd()`**——那是 DSH 进程启动目录，不是会话工作区，会圈错地方 |
| 零依赖，不 import 任何 `@deepseek-ai/*` | 插件装在 profile 的 `node_modules` 里，那里解析不到 dsh 安装目录下的包 |
| 用 `realpath` 规范化目标（不存在的路径则解析最近的已存在祖先） | 穿透**已存在**的符号链接。模型自己造不出符号链接（无 shell，`write` 只写文本），但目录里本来就可能有一个 |
| 拿不到会话 cwd 时**拒绝** | 失败关闭。放行是静默失败、拒绝是吵闹失败——安全控制该有后者 |

**单元验收 —— 26 PASS / 0 FAIL**（`node dsh/plugins/fs-readguard/test.mjs`，不启动 DSH）

覆盖：工作区内读放行（绝对/相对/根本身/不存在的目标）、技能根放行、
拒绝 `.env` / `account.db` / `~/.dsh/.credentials.yaml` / `/proc/self/environ` / `/etc/passwd`、
相对路径向上穿越、绝对路径夹 `..`、穿过已有符号链接、**前缀陷阱**（`alice` 不能读 `alice-other`）、
父目录不是工作区、`read_image` 同样受管、`write`/`edit`/`skill`/MCP 不受本守卫管辖、
参数缺失交还工具校验、缺 cwd 时失败关闭。

**集成验收 —— ✅ 已通过（真实 DSH 进程内实测）**

在一次性 profile 上跑通（`rgtest`，从 headless 模板创建；headless **不加载 `dsh2server`**，
因此不注册到中转、不干扰正在运行的实例）：

| 输入 | 结果 |
|---|---|
| `read ./hello.md`（会话工作区内） | ✅ 正常返回内容 |
| `read <项目根>/.env`（工作区外） | ✅ `Error: [readguard: read denied] …/.env 不在允许读取的范围内，已拒绝。本会话只允许读取它自己的工作区，以及技能说明文件。` |

这证明了完整链路：插件在真实 DSH 启动中被加载 → 守卫注册进真实工具流水线 →
拿到真实 `ToolExecution` 的字段 → 正确放行工作区内、拒绝工作区外。

**做这个测试的关键技巧：把 `DSH_HOME` 指向工作区内部**（`poc/rg-home`），
而不是 `~/.dsh`。这样 DSH 启动时写的 `cordis.yml`、profile、session、storage 全落在工作区内，
**不需要任何越界权限**（沙箱是 `workspace-write`，写 `~/.dsh` 会被拒）。
凭据从 `~/.dsh/.credentials.yaml` 拷入临时 DSH_HOME（读不受限），测完立即删除。

| 结构层验收（此前已验） | 结果 |
|---|---|
| profile 能解析到模块 | ✅ `resolve('dsh-fs-readguard')` → 仓库内路径 |
| `apply()` 真的挂上守卫 | ✅ |
| 真实 `exec` 字段名 | ✅ 与 `ToolExecution` / `agent.session.header.cwd` 一致 |
| preset YAML 结构 | ✅ |

**安装方式与本地开发的三个坑**：

1. **必须用全局 Node 版 `dsh`，不要用 `venv/bin/dsh`。** 后者是 **Python runtime wheel**，
   实测**缺少 `@deepseek-ai/dsh-session-title-llm`**（`venv/lib/python3.14/site-packages/
   deepseek_harness_runtime/runtime/node/node_modules/@deepseek-ai/` 下不存在），
   导致**任何 profile 都无法启动**，报 `Cannot find package '@deepseek-ai/dsh-session-title-llm'`。
   该错误与本插件无关，是 wheel 打包不完整。能用的那个在
   `~/.nvm/versions/node/<ver>/bin/dsh`。
2. **Python runtime 版必须显式 `export DSH_HOME`。** 它绝不隐式使用 `~/.dsh`，
   不设会报 `the Python runtime command requires an explicit DSH_HOME`。
   在 DSH 会话内该变量已由 harness 设好，所以从会话里跑不会遇到——换到普通终端才会突然失败。
3. **在 DSH 会话内装插件会失败。** `pnpm` 要 chmod profile 里的 bin shim，
   而 profile 在工作区之外，`write` 沙箱拒绝（`ERR_PNPM_CMD_SHIM_CHMOD` / `EPERM`）。
   把 `DSH_HOME` 指到工作区内可绕开（见上）。

**验收**

- `read` / `read_image` 读 `.env`、`account.db`、`~/.dsh/.credentials.yaml`、`/proc/self/environ` 全部被拒
- `read` 读 `Templates/` 下的文件被拒（未列入白名单的默认结果）
- `read` 能读 `Skills/consult/references/*.md`（否则 consult 跑不动 —— 这条是防"白名单写太窄"）
- `write` 仍只能写 `Account/<user>/` 之下
- 自动检查：扫 `agent.cordis.yml`，出现禁止工具即失败
- DSH 进程自身不受限 → 启动与运行不受影响

**为什么不选 systemd 命名空间 / 第二 OS 账号**（记录决策，避免重复讨论）

| | 读白名单 | 第二 OS 账号 | systemd 命名空间 |
|---|---|---|---|
| 覆盖 `/proc/self/environ` | ✅ | ✅ | ❌ |
| 跨平台（本地 macOS 也生效） | ✅ | ✅ | ❌ Linux only |
| 需要改部署与启动方式 | ❌ | ✅ | ✅ |
| **对当前手工启动的实例生效** | ✅ | ✅ | ❌ **完全无效** |
| 弄崩 DSH 启动的风险 | **无** | 中 | 高（`ProtectHome` / `ProcSubset`） |
| 造成"假装加固了"的风险 | **无** | 无 | **高** |

两条决定性理由：

1. systemd 命名空间**只在由 systemd 拉起时生效**。而当前 DSH 实例是手工 `dsh --profile` 启动的
   （`Relay/adapter.py` 里没有任何 `Popen`/spawn，只有 `wait_for_instance()` 等实例自己注册）。
   加了 unit 而不改启动方式等于没加，还会给人"已经加固"的错觉。这是原方案最大的风险。
2. `ReadOnlyPaths=/opt/letsplaydnd` 与存档写入**直接冲突**——存档就在 `Account/<user>/Saves/`，
   在项目根之内。必须再配 `ReadWritePaths`，漏一个就是"存档静默写失败"。

读白名单不碰 DSH 进程自身的读，所以**不可能**把 DSH 自己的启动依赖掐掉——这是它与 systemd 方案最大的风险差别。

**已确认**：DSH 实例连模型用的 key 存在 `~/.dsh/.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY`，
是**操作者的一把、所有用户实例共用**——按用户隔离是未来目标，当前未实现，见 §10.5。
它落在白名单之外，因此是 P5-1 的**第一个真实目标**。

#### P5-2 存档快照实现说明

`SaveSnapshots(root)`，按存档 `data/` 目录各建一颗**裸库**（`git init --bare`），
库路径 = `root/<sha1(绝对工作目录)[:16]>.git`。

- 库在**工作区之外**：模型对工作区有写权限，`.git` 若在存档内则可被模型改写，快照失去意义。
- 只快照调用方给定的 `work_tree`（通常是 `<存档>/data`），不含 `chat.db`（二进制、每回合都变，会让仓库膨胀）。
- `commit(work_tree, msg) -> rev | None`：与"当前位置"相比无变化则返回 `None`。
  基准点是库内 `POSITION` 文件，**不是 HEAD**——`rollback` 刻意不动 HEAD（历史不丢、可再往回滚），
  若拿 HEAD 当基准，"回滚后本轮无改动"会被误判成有变化，生成重复提交。
- `rollback(work_tree, rev)`：`read-tree --reset -u <rev>` + `clean -fdq`。
  不用 `checkout <rev> -- .`（不删目标版本里不存在的文件，`clean` 也清不掉），
  也不用 `checkout <rev>`（HEAD 会 detached）。
- 提交用 `--allow-empty`：模型可能恰好把文件改回上个提交的样子，此时索引与 HEAD 相同，
  普通 `commit` 直接报错，但"位置"确实移动了，必须记下。

**验收结果**：22 PASS / 0 FAIL（含回滚、撤销回滚、重做、子目录、新增文件清除、空提交抑制、多存档隔离）。

**遗留**：尚未接入回合流程（每回合提交、回滚入口属 P6）。

### P6 game 流程迁移

**内容**：将 `System/game/game_zh.py` 的流程改写为 skill。按类别分派提示词由模型执行，SKILL 正文约束其只读取对应 `references/` 文件。存档由模型直接写入，以 P5 快照兜底。不保留 `plan_panel_update` 类 gate 工具。

**验收**：常规回合端到端可玩；异常写入可回滚。

**依赖**：P5。

### P7 battle

暂缓。

---

## 7. 迁移策略

新旧路径并存，逐流程切换：

1. Flask 保留现有 `System/consult`、`System/game` 路径
2. 新增 DSH 路径，由开关选择
3. 先切换 consult，验证后再切换 game 常规回合
4. battle 不变更

回退通过开关完成，无需 revert 代码。代码级回退锚点：tag `v0.9-working`。

### 7.1 清理策略

**`Prompts/` 下的文件在整个项目实测完成前一律保留**，即使内容已迁入 `Skills/`。
新路径尚未全量验证，旧文件是回退与对照的依据；待 P6（game）也测通后再统一清理。

`Skills/` 内部的重叠文件不受此限：`Skills/rag-query/` 因与 `consult/references/rag-query.md`
高度重叠且会导致 skill 目录出现两个技能，已在 P2 删除（内容已迁入，git 中可恢复）。

---

## 8. 约束

1. **工具面最小化**。不挂载 shell、subagent、workflow、web。工具级读围栏的完备性以「无 shell」为前提。
2. **快照仓库位于模型写围栏之外**，否则失去保护意义。
3. **`.env`、`account.db` 不得处于 DSH 进程可达范围**。二者泄露等价于全部用户会话与 API Key 泄露。
4. **RAG adapter 与 RAG 实现同仓库、同提交**。
5. **DSH profile 必须是 web-capable**。`sdk` / `sdk-minimal` 不提供 `sessionController`，`dsh2server` 的会话能力会退化。
6. **中转服务器的实例 key 按用户隔离**。一个 key 只能访问其对应实例，禁止跨实例操作。

---

## 9. 待验证事项

- ~~模型在极简工具面下能否稳定完成三段流程~~ → ✅ 已由 P3.5 consult 端到端实测覆盖
- 无 approver 时沙箱提权是否失败关闭 → **移交 P6**（需要一次被拒写入才能触发）
- `dsh2server` 在自定义 web-capable profile 下的能力集合是否满足需求 → **移交 P6**（在完整游戏流程里才用得全）

---

## 10. 遗留问题（原系统，本次不处理）

来源：`Content/开发手册.md`，以及本次调研期间发现但未修复的问题。

**处理原则**：下列问题**不影响迁移的正确性**，只记录、不修改。仅当某问题会阻塞对接或导致严重报错时才动手（条件见 §10.4）。

### 10.1 迁移会顺带解决的

| 问题 | 手册位置 | 迁移如何解决 |
|---|---|---|
| MCP 每次调用都要重连，耗时过长 | 工具优化 | 改为常驻的 HTTP MCP 服务（§5.1），调用不再建立连接 |
| 工具调用未并行，RAG 等待时间长 | 工具优化 | DSH 调度器对**声明为并发安全**的工具并行分发 |
| stage 顺序与工具分发硬编码在 Python | 本次调研 | 改为 SKILL.md 描述流程，由模型推进（§2.1） |

### 10.2 迁移不解决、仍然存在的

| 问题 | 手册位置 | 说明 |
|---|---|---|
| 战斗分支环节复杂、响应慢、中途报错无良好重启 | 战斗分支 | battle 暂缓（P7） |
| 长期记忆缺失 | 长期记忆 | 手册中两种方案均未落地，需单独设计 |
| 隐藏剧情 / 章节结束 / 自定义开始 | 对应章节 | 主要是游戏设计问题，非实现问题 |
| 添加队友 | 添加队友 | 未实现；手册建议用预制角色而非临时生成 |
| 无免费额度开关（供无 key 用户试玩） | 免费额度 | 设计意图是"每用户一实例、key 自备"，但**该意图尚未实现**，见 §10.5 |
| 存档级 / 全局 rules 不可手动添加 | Rules | 未实现 |
| 笔记区 MD 渲染差（尤其表格） | MD渲染 | 未实现 |
| 同账号不可多设备登录 | 安全 | 未实现；手册判断优先级低 |
| XSS 防护不完整（页面未加载 DOMPurify） | 防护 | 未实现。**迁移后风险不降**：模型输出经中转进入前端，仍需同一套清理 |
| 无 CSRF token | 防护 | 未实现 |
| 无 HTTPS / Secure Cookie / 安全响应头 / 频率限制 | 防护 | 未实现 |

### 10.3 本次调研新发现（原系统问题，未修）

| 问题 | 位置 | 影响 |
|---|---|---|
| `FLASK_SECRET_KEY` 一钥两用，派生方式可预测 | `server.py` 的 `_fernet()`：`raw.ljust(32, b"0")[:32]` | 同一密钥既签 Session 又作 Fernet 密钥；若密钥短于 32 字节用 `0` 补齐会稀释熵。建议拆分用途 |
| 前端 SSE 无断线续传 | `UI/js/chat-view.js` 用 `fetch` + `body.getReader()` 手动解析，非 `EventSource` | 一轮可能运行 30 秒以上，断线即丢失前半段。**已列入 P4 验收**，不算遗留 |
| `account.db` 与 `.env` 同处项目根，均可被 DSH 进程读到 | 部署结构 | 见 §8 约束 3；**改由 P5-1 读白名单解决**（原定的 systemd 命名空间隔离已降级暂缓，理由见 P5-1） |
| **RAG 对「火球术」召回不准** | `RAG/`（索引与切块） | P3.5 实测：查询 `火球术 豁免 伤害` 返回的首块虽被标注为火球术，正文却是**另一条法术**（光耀伤害、d8 缩放），**不含火球术的数值**。模型据此正确判定"未命中"并按纪律声明"非规则书引用"。属召回/切块质量问题，与迁移无关 |

> RAG 召回这条值得单独留意：它直接影响「规则回答是否可信」，而且是**旧系统就存在**的问题——迁移只是让它更显眼了。按 §10.4，此处只记录不改。

### 10.4 触发修复的条件

出现以下任一情况时才动这些遗留问题：

- 阻塞对接（例如前端取不到必需字段）
- 导致严重报错（进程崩溃、数据损坏）
- 安全类问题在公网多用户场景下被实际利用

### 10.5 迁移引入的行为落差（尚未补齐）

> 本节记录的是**这次迁移自己引入的**行为变化，不属于 §10.3 的"旧系统问题"。
> 排查依据是"设计意图 vs 当前代码实际行为"，不是猜测。

#### 凭据未按用户隔离 —— **上线前必须解决**

| | 旧路径（非 DSH） | 现状（DSH 路径） |
|---|---|---|
| 取 key | `get_user_api_key(username)`（`server.py:867`） | **不取**：`server.py:863-865` 在取用户 key **之前**就分流到 DSH |
| 实际使用 | 该用户自己的 key | DSH 实例自身的凭据 = `~/.dsh/.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY`（**操作者的一把**） |
| 未配 key 的用户 | 400 `api key unavailable` | **照常可玩，费用记在操作者头上** |

证据链：`server.py:824` 注释（"DSH 侧不需要 Flask 这边的用户 API Key——每个 DSH 实例用自己的凭据"）、
`server.py:863-865` 提前 `return`、`Relay/adapter.py:113` 的 `session.create` 只传 `cwd`、
两个 profile patch（`dsh/profile.patch.yml`、`~/.dsh/profiles/letsplaydnd/cordis.patch.yml`）均未指定模型与 key。

**成因**：DSH 的凭据存储是 **DSH_HOME 级**，不是会话级。`session.create` 能选 preset、能选 model，
但 key 来自进程的 credential store，**没有"本次会话用这把 key"的入参**。

**因此"每用户一把 key"必然推导出每用户一个 DSH_HOME**（`update.md` §1.1 的 `dsh-<name>` 形态），
它与「每用户实例自动创建 / 端口分配」是**同一件事**，必须合在一起做，不要拆成两步。

**两条禁令**：

1. 不可只做"没 key 就拒绝开始游戏"的门禁。那只做了一半：强制用户配 key，实际仍用操作者的 key 跑，**比现状更误导**。
2. **半成品不得部署。** 当前状态下，任何登录用户都能消耗操作者的额度。

**与 P5-1 的关系**：补齐之后，每个实例的 key 就落在**它自己的 DSH_HOME** 内，
而那是典型的"进程必须持有、模型因此也读得到"的一类文件——P5-1 读白名单是唯一挡得住它的东西。
两者应一起上：只做隔离没有白名单，等于每个实例都能把自己的 key 念出来。

**本地测试不受此限**：本机是同一操作者，共用一把 key 无影响。

