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
| 中英双语 | **consult 已双语**（`consult-zh` / `consult-en`，见 §2.2「双语化」）；game 与 battle 仍仅中文 |
| DSH 插件**开发** | ⚠️ **已偏离，见 P5-1 / P6**。原定"不编写任何 DSH 插件"，实际自研了两个：`dsh/plugins/fs-readguard`（读路径围栏——DSH 任何一层都不提供，沙箱只管写）与 `dsh/plugins/tool-list-dir`（目录列举工具——官方只给 `read`/`read_image`/`write`/`edit`，没有把"列目录"交给模型的工具）。除此之外仍只安装并使用第三方插件 |

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
  Store/                    # 数据层：存档 meta + 两个 chat.db 的读写（从 System/ 逐字抽离）
  UI/
  RAG/
  Dice/
  Skills/
    consult-zh/
      SKILL.md
      references/
    consult-en/             # 结构与 consult-zh 逐节对应
    game-zh/                # 游戏流程（四步 + references/）
    game-en/                # 占位，英文流程未编写
  MCP/
    mcp_server.py
  Relay/                    # dsh2server 协议的服务端实现
  dsh/
    profile.patch.yml
    units/

/var/lib/letsplaydnd/history/         # 存档快照裸库（工作区之外）
/var/lib/letsplaydnd/users/<name>/    # 每用户 DSH_HOME（0700）
```

**不在服务器上**（本地保留便于回看，`.gitignore` 已忽略）：`System/`（旧流程编排）、
`Prompts/`（旧提示词）、`Tools/`（旧工具实现）。服务器侧的开关已默认打开，旧流程分支不会执行；
`server.py` 需要的数据层函数已抽到 `Store/`，与 `System/` 无 import 依赖（实测把三者全挪走仍可运行）。

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

**位置**：`Skills/<name>/`，与项目并列存放。当前为 `Skills/consult-zh/` 与 `Skills/consult-en/`。

**结构**：

```
Skills/
  consult-zh/
    SKILL.md            流程总纲
    references/         各阶段指令，按需读取
      decision.md
      rag-query.md
      output.md
  consult-en/           与 consult-zh 结构逐节对应，内容为英文
  game/                 与 consult 并列（P6）
    SKILL.md
    references/
```

**约束**：

- 目录式 bundle：被扫描的根下直接是 `<name>/SKILL.md`；**不支持嵌套** `**/SKILL.md`
- frontmatter 必填 `name`（kebab-case，且与目录同名）与 `description`；可选 `whenToUse`、`disable-model-invocation`、`user-invocable`
- **`references/` 下的文件不会自动进入上下文。** skill 工具返回 `<skill_resources>` 块，给出该 skill 的**绝对基目录**并要求按基目录解析相对路径；模型须自行用 `read` 读取。因此 SKILL.md 正文必须显式写明要读哪些文件
- 语言隔离：中文与英文为独立目录（`<name>-zh` / `<name>-en`），**不在同一 `SKILL.md` 内做语言分支**。已落地：`consult-zh` / `consult-en`，选择依据是用户当前输入的语言，见 §2.2「双语化」

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
| P5 | 安全加固 | P3.5 | 进行中（key 白名单、存档快照、读白名单、**每用户凭据隔离** 已完成；剩回环租户隔离等第二段，见 §10.5） |
| P6 | game 流程迁移 | P5 | ✅ **端到端联调已通过**（六轮：五类 + 移动，真实链路，工具错误 0）；剩两个验收项待测（对账、半成品叙述压力测试）与提示词精修 |
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

**内容**：编写 `Skills/consult/`（后拆为 `consult-zh/` + `consult-en/`），迁移 `Prompts/consult/` 内容至 `references/`。

**依赖**：P1。

**结果**：

```
Skills/consult-zh/        中文版（原 Skills/consult/，见下方「双语化」）
Skills/consult-en/        英文版
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
| 可被发现 | ✅ `consult` 出现在会话的 skill 目录中；双语化后为 `consult-zh` / `consult-en` |
| 热加载 | ✅ 修改 skill 无需重启 |
| **references 可读** | ✅ skill 工具返回 `<skill_resources>` 块，给出**绝对基目录**并要求按基目录解析相对路径；实测可读 |

**要点**：`references/` 下的文件**不会自动进入上下文**，SKILL.md 必须显式要求模型用 `read` 读取。此点已实测确认。

**待补**：完整「判断 → 检索 → 输出」链路需 `search_rules` 工具可用，属 P3 验收。

#### 双语化（consult-zh / consult-en）

**语言选择规则**：**只看用户当前这一次输入的语言**，不做硬切割、不读存档设置。

- `Skills/consult-zh/`：description 里写明"如果用户当前输入是中文，使用该 skill"
- `Skills/consult-en/`：对应写 "If the user's current input is in English, use this skill"
- 同一句话的两种语言交替出现时，以**最近一条用户输入**为准，不会中途硬切

**为什么 consult 适合先做**：consult 不碰存档文件，切语言没有后果（没有"之前所有文本都是原语言"的问题）。game 流程不同——它有成篇的历史叙述，中途切换需要先暂停并询问用户是否要翻译既有内容（用户会在元对话里加这个指示）。这也是先完善 consult 机制的原因。

**英文素材的来源与一处必须说明的差异**：

| 英文 reference | 来源 |
|---|---|
| `decision.md` | `Prompts/consult/decision-en.md` 的 Judgement 部分 + 中文版对照补齐 |
| `output.md` | `Prompts/consult/output-en.md` + 中文版对照补齐 |
| `rag-query.md` | `Prompts/consult/decision-en.md` 的 Core Mechanism / Query Input / Multiple Queries 三节 + 中文版对照补齐 |
| `SKILL.md` | 无英文来源（`Prompts/` 只有 `skills-zh.md`），按中文版对照重写 |

⚠️ **`Prompts/consult/` 里没有 `rag-query-en.md`，也没有 `skills-en.md`**；而且英文的 `decision-en.md` **把 decision 与 rag-query 的内容混在一个文件里**（中文是拆开的）。因此英文 skill 是按**中文的三段结构**重新组织的，那三节从 `decision-en.md` 移到了 `rag-query.md`。两边结构逐节对应（decision 4 节 / rag-query 3 节 / output 3 节），已脚本校验。

**语言库的选择（`search_rules` 的 `language` 参数）**

RAG 有两套向量库与两套 embedding 模型：

| `language` | collection | embedding | 空结果文案 |
|---|---|---|---|
| `"zh-CN"` | `dnd_rules_zh` | `BAAI/bge-small-zh-v1.5` | 未找到足够相关的规则。 |
| `"en"` | `dnd_rules_en` | `BAAI/bge-small-en-v1.5` | No sufficiently relevant rules found. |

原先 `MCP/mcp_server.py` 把语言**写死**为 `DEFAULT_LANGUAGE`，模型无法选择，英文 skill 只能查到中文库。现改为 `search_rules(query, context_label, language)`，`language` **必填、无默认值**：

- 中文 skill 传 `language="zh-CN"`，英文 skill 传 `language="en"`
- **不设默认值**：漏传会让工具调用直接报错，模型随即补上——刻意的吵闹失败
- 若给默认值，漏传就会静默查到另一种语言，且失败**隐形**
- **取值用 enum 钉死**：签名用 `Literal["zh-CN", "en"]`（`MCP/mcp_server.py` 的 `RuleLanguage`），
  schema 生成 `enum`，模型在协议层只能从两个合法值里选
- `Tools/consult/rag_tools_en.py` 是旧系统的人工实现（两套工具、语言焊在工具里），本次未采用，仅供对照

**为什么必须用 enum，而不只是提示词约定**——`RAG._normalize_lang` 的容错方向很危险：

```python
lang = (language or "zh-CN").lower()
if lang.startswith("en"): return "en"
return "zh"          # 任何不以 en 开头的值，一律退回中文库
```

实测各种写法的落点：

| 传入 | 实际库 | 备注 |
|---|---|---|
| `"zh-CN"` / `"中文"` / `"zh"` / `""` | zh | `"中文"` 是对的，但纯属碰巧 |
| `"en"` / `"English"` / `"en-US"` / `"EN"` | en | `"English"` 也是碰巧（`startswith("en")`） |
| **`"英文"`** | **zh** | ❌ **英文 skill 若填"英文"，会静默查到中文库** |

也就是说错值**不一定报错**，还可能静默走错库——正是最难受的失败模式。
改 enum 后实测：传 `"英文"` 被拒，返回
`Input should be 'zh-CN' or 'en' [type=literal_error, input_value='英文']`，
错误信息里带合法取值，模型可以据此自纠。

**查错库的后果已经被 `output.md` 兜住**（这一条决定了上面那个参数该有多严）：

`output.md` 把「没有返回文本」与「阅读后认为片段与用户需求**完全不匹配**」**合并为同一条规则**——
都退到常识回答，且**必须向用户声明这不是规则书的直接引用、可能有误**。
所以查错库不会导致"把错误规则当权威讲出来"，而是**可归位的降级**：用户拿到的是基于常识的回答 + 声明。
剩下的灰区只有「完全不匹配」与「部分相关」之间——但查错库时返回的片段是**另一种语言**的、
且**相似度分更低**（实测无意义查询 `[距离分数: 0.60]`，正常命中 0.70），两个信号都摆在模型面前。

因此：**查询与库对应**是质量要求，不是正确性要求。这也是为什么 `language` 用必填（防漏传）
而不是靠更复杂的机制去保证对应。

> **改动生效范围**：MCP 工具的 schema 在**服务启动时**生成、并 DSH 实例在**启动时**拉取缓存。
> 因此改 `MCP/mcp_server.py` 的工具签名后，必须**重启 MCP 服务**（:8790）**并重启 DSH 实例**，
> 否则模型看到的仍是旧 schema。这点已在本次改动中实测：只重启 MCP 后，curl `tools/list`
> 才看到新的 `required` 列表。

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
| skill 目录 | ✅ 只出现预期 skill（`consult`；双语化后为 `consult-zh` / `consult-en`） |
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
| `Skills/` | ✅ | ❌ | **必需，不能漏**：`Skills/consult-zh/SKILL.md:9-10` 要求模型"用 read 工具读取对应文件"，不给它读 consult 直接跑不动 |
| `Templates/` | ❌ | ❌ | **暂不列入**（未列入白名单即不可读）。模板是「开局」阶段由 Flask 侧复制成存档，模型没有读写必要。以后可能需要只读（例如游戏自建人物时参考格式），届时再加 |

只有两个根。未列入的路径**默认不可读也不可写**——这正是白名单的意义，不需要为 `Templates/` 写任何"禁止"规则。

> **⚠️ 根随流程不同**（P6 设计确定）：白名单的第一个根是**会话 cwd**，而两个流程的 cwd 不同。
> 下表是**目标状态**：
>
> | 流程 | 会话 cwd（目标） | 实际可读写范围 |
> |---|---|---|
> | 规则咨询 | `Account/<用户名>/Saves/consult/data` | **只有咨询的 `data/`** |
> | 游戏回合 | `Account/<用户名>/Saves/<存档>/data` | **只有该存档的 `data/`** |
>
> **⚠️ 咨询的 cwd 需要改**：现状是 `server.py:829` 传的是 `Account/<用户名>`，于是读白名单允许
> **咨询读取该用户的全部存档**（`Account/<用户名>/Saves/**`）——而咨询一个存档文件都不需要读。
> 改成 `Saves/consult/data` 之后，两个流程的 cwd 同构、边界一致。
>
> 另一个后果：模型读不到存档根的 `chat.db`。这是想要的——`chat.db` 由适配层写，不是模型的活。
>
> **`list_dir` 与这张表同圈**：它的上界也是会话 cwd（不是存档根），所以"能读的就能列"。
> 见 P6 第 10 条与 `game-flow-design.md` §9.3.1。

注意读写根**故意不同**：`Skills/` 必须可读但不可写，否则模型能改自己的指令。
本项是在现有 `workspace-write`（只管写、根 = 会话 cwd）**之上补一条读规则**，不替换它。

**不变量**（是白名单的成立条件，不是附加项）

> 本预设不得引入任何可执行代码的工具（bash / pwsh / 带 shell 的 subagent / 等价物）。
> 引入即等于同时拆除读白名单。

理由：白名单是**可信代码中的策略**，只在"模型只能发工具调用、没有第二条通往文件系统的路"时完备。
DSH `dsh-fs-sandbox` README 的原话：围栏是策略而非内核边界，**只有目标路径不可信**，
因此「规范化后检查包含关系」就是该接口的完整答案；不可信代码的内核级隔离由 `ctx.shell` 负责。
当前预设工具面 = `tool-fs`（`read`/`read_image`/`write`/`edit`）+ `tool-list-dir`（`list_dir`）
+ `skill-filesystem` + `tool-skill`，
没有 bash、web、subagent、`tool-fs-search`；MCP 工具运行在我们的进程里，不是文件系统通道。**前提成立。**
（`list_dir` 只列文件名、不读内容，且自己带同一套包含性检查，不削弱这条不变量。）

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
| 零依赖，不 import 任何 `@deepseek-ai/*` | **硬约束**：插件以 `link:` 装入 profile，真实路径仍在仓库里，Node 从**仓库**向上找 `node_modules`，走不到 `~/.dsh/profiles/node_modules`（那里才有指向 dsh 安装目录的符号链接）。实测 `ERR_MODULE_NOT_FOUND` |
| 用 `realpath` 规范化目标（不存在的路径则解析最近的已存在祖先） | 穿透**已存在**的符号链接。模型自己造不出符号链接（无 shell，`write` 只写文本），但目录里本来就可能有一个 |
| 拿不到会话 cwd 时**拒绝** | 失败关闭。放行是静默失败、拒绝是吵闹失败——安全控制该有后者 |
| **不拦只读工作区目录的专用工具**（P6 新增） | 它的包含性检查**内建在实现里**（复用同一套 containment），范围是**构造**出来的，不需要经过拦截层。但 ⚠️ **若将来挂 `dsh-tool-fs-search`（`glob`/`grep`），必须同时把它加进本守卫的受管清单**——`glob` 返回路径、`grep` 返回匹配行，都是读通道，不拦就能扫整个文件系统 |

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
- `read` 能读 `Skills/consult-zh/references/*.md` 与 `Skills/consult-en/references/*.md`（否则 consult 跑不动 —— 这条是防"白名单写太窄"）
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

**接进回合流程（P6，已实现）**：每回合**出稿之后**提交一次（`Relay/adapter.py` 的 `on_turn_end` 回调），
根目录走 `DSH_SNAPSHOT_DIR`（生产 `/var/lib/letsplaydnd/history`，本地默认 `<仓库>/.snapshots`，已 gitignore）。
回滚入口：`GET /api/game/snapshots`、`POST /api/game/rollback`。

三条工程约定（都在接线时落地）：

| 约定 | 原因 |
|---|---|
| 快照异常**只记日志，不影响这一轮** | 正文已经产出并落库，git 出问题不该让玩家看不到稿（实测：抛异常时 `done` 照常下发） |
| 按存档串行（`_snapshot_lock`） | 前端已锁发送，但两个标签页仍可能同时进来，而 git 的 index 不是并发安全的 |
| `rev` 只接受"像版本号"的字符串 | git 参数是列表、不经过 shell，但以 `-` 开头的 rev 会被当成 git 选项 |

**实测开销**（真实存档 20 文件 / 11.6 KB）：首次提交 235 ms（含 `git init`）；
**本回合无改动 71 ms 且不产生提交**；改 1 个文件 136 ms、仓库 +811 字节；
再 20 个回合仓库 +15 KB（约 800 字节/回合）。相对一次 LLM 回合（秒级）可忽略。

### P6 game 流程迁移

**内容**：将 `System/game/game_zh.py` 的流程改写为 skill。按类别分派提示词由模型执行，SKILL 正文约束其只读取对应 `references/` 文件。存档由模型直接写入，以 P5 快照兜底。不保留 `plan_panel_update` 类 gate 工具。

**验收**：常规回合端到端可玩；异常写入可回滚。

**依赖**：P5。

> **详细设计见 `game-flow-design.md`**（独立文档）。本节只留摘要，避免两处描述漂移。
>
> 设计主体已定：**§9 全部裁决完毕，无待确认项**。**端到端联调已通过**（`game-flow-design.md` §10 有逐项结果），
> 剩两个验收项（对账、半成品叙述压力测试）与提示词精修。
>
> **收尾已完成**：数据层从 `System/` 逐字抽到 `Store/`（`server.py` 不再依赖 `System/`），
> 开关 `DSH_CONSULT_ENABLED` / `DSH_GAME_ENABLED` **默认打开**（`=0` 可本机回退），
> `System/`、`Prompts/`、`Tools/` 已不再推送（`.gitignore`），每用户实例自启 `DSH_INSTANCE_AUTOSTART` 默认开。
>
> **语言路由（已实现）**：`server.game_skill_for(save_meta["in_game_language"])` → `game-zh` / `game-en`，
> 适配层把 `/<skill>` 注入当轮提示词（`Relay/adapter.py` 的 `skill` 参数）。
> 只有以 `en` 开头走英文，其余一律中文（与 `RAG._normalize_lang` 同约定）。
> `Skills/game-en/` 目前是**占位**（正文写明尚未编写）；也没有 `en` 模板，所以现在还建不出英文存档。
>
> **已验收**（真实 headless 会话，非模拟）：`list_dir` 单测 15/15；真实会话里模型连续调用它 6 次
> （`{"path":"."}`、`world`、`characters`、`plot`、`characters/allies`、`status`），
> 输出均为相对路径 + 目录在前 + 点开头项不显示，且返回的路径直接被后续 `read` 用上；
> 同一回合 `/game-zh` 注入成功（模型按 `read-panel.md` → `classify.md` → `exploration.md` 的顺序读）。
> 验收脚手架与解会话日志的脚本见 `poc/dump-session.mjs`（`poc/` 已被 gitignore）。
>
> ⚠️ **E2E 的一个坑（已确认，避免重踩）**：**headless 组合不挂 agent preset**——
> `agentPresets.mount()` 只在 `dsh-api-session-controller`（web-app 的行）里被调用。
> 所以 `--profile headless` 下无论怎么配 roster，会话都不会用我们的 preset（会话头里 `agentPreset` 为空，
> 模型看到的是 DSH 自带的编码助手工具面，`readRoots` 之类的预设配置也都不生效）。
> 要在真实会话里验**预设本身**，必须走 web 实例（Flask → Relay → `agentPreset.select`），
> 也就是 P6 接线后的路径；headless 只适合验**插件本体**（把预设的行直接 `insert` 进 patch）。
> 其中最重要的三条已定的策略：
> 1. **不注入上下文**——面板全部由 skill 约束模型自行读取（§4.2）。
>    插件只用来补**工具**（`list_dir`）与**围栏**（`fs-readguard`），没有、也不会有注入上下文的插件
> 2. **状态真源不是"存档为准"**，而是"本回合叙述改变了的以叙述为准，否则以本回合读到的存档为准，冲突时以叙述为准并补写存档"（§4.3 / §4.5）
> 3. **变更清单**（`> 面包：3 → 2`）由模型在正文里产出，充当 update 的待办清单，替代被丢弃的 `plan_panel_update`（§4.4）
>
> **已裁决的十项**：
> 1. **人称一律第二人称**（`interaction.md` 那句「全知第三人称」是错的，废弃）
> 2. **battle 当做不存在**——不写交接、不做占位，本流程不涉及战斗
> 3. **地点更新 reference 由 `4.2` + `4.3` 两稿合并新写**（不是二选一：它们是同一件事的两稿）
> 4. **按流程隔离 skill 的方式：适配层注入，不靠两个 preset**（原"两个 preset + 机械检查"的方案已作废）。
>    现状：**只有一个 preset** `letsplaydnd`；`Skills/` 平铺（`consult-zh` / `consult-en` / `game-zh` / `game-en`）。
>    隔离靠**注入的 skill token**：game 由适配层按存档语言注入 `/game-zh` 或 `/game-en`（已实现），
>    consult 不注入、由模型按用户输入语言在目录里自己选。
>    所以不需要两份近 100 行的 YAML，也不需要那个"除 skill 根外完全相同"的机械检查。
>    隔离的是**流程**（game 与 consult 挂不同 skill），**不是语言**：`consult-zh` 与 `consult-en` 都可见。
>    详见 `game-flow-design.md` §8「语言路由」
> 5. **`current_info.json` 由模型直接改写**（④ 阶段），可整体重写——旧系统由 Python 逐字段改，
>    原因是当时**没有自审也没有回滚**（直接重写容易写出非法 JSON，例如加注释）。
>    现在有快照回滚 + 覆盖前必须先读，所以不再需要那个限制
> 6. **元对话不叠加 DM 注记**（保留旧行为）——其余四类是有效游戏动作，叙述里的「你」= 游戏角色；
>    元对话是**暂停游戏、直接与玩家对话**，加 DM 扮演词会把玩家与角色混淆
> 7. **语言**——`search_rules` 的 `language` 参数**保留且必填**；consult **维持按用户当前输入语言选变体**；
>    game 的语言**开局确定且不可更改**（已有存档文件是原语言的，全翻译不可能）。本期不处理"语言切换"。
>    **语言由「选哪个模板」决定**：模板清单 `Templates/game/meta.json` 的 `in_game_language` 在建存档时直接拷入存档 meta，
>    玩家事后无法修改（UI 的语言开关只改**界面语言**与 `consult`，**不碰 `game_*`**）。
>    因此加 `game-en` **零新增存储**；但**必须读存档的 `in_game_language`，不能读账号的 `settings.json.language`**（后者是界面语言）。
>    此前"删掉 `in_game_language`"的计划**已撤销**。见 `game-flow-design.md` §9.2.3
> 8. **主线 `plot/cur_main_plot.md` 本期不设计**——照搬现状（可读、不更新），先让整条流程跑起来
> 9. **软锁（团灭）当做不存在**，删掉这个前置——团灭属于战斗，其他游戏逻辑不会死亡
> 10. **加一个只读工作区目录的小工具**——极简模式的 `read` 只读文件、给目录报 `FS_NOT_REGULAR_FILE`，模型列不出目录；
>     不挂 `dsh-tool-fs-search`（要额外挂**不受沙箱约束**的子进程后端去 spawn `rg`，且 `grep` 是内容通道），
>     也**不引入代码执行/PTC**（官方明确其权限**等同 bash、可访问 Node API** → 等于拆除 P5-1 读白名单）。
>     **已实现为进程内 DSH 插件 `dsh/plugins/tool-list-dir/`**：根固定为会话 cwd（模型只传相对路径），
>     两道包含性检查（词法 + realpath），只列文件名不读内容。
>     这一版**推翻了原先"MCP 工具"的决定**——MCP 拿不到会话上下文，只能让模型自己报 `base`，
>     实测能拿别的存档当 base 列出其文件名。详见 `game-flow-design.md` §9.3.1

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

#### 凭据未按用户隔离 —— 第一段已完成，第二段待做

| | 旧路径（非 DSH） | 之前（DSH 路径） | 现在（已实现） |
|---|---|---|---|
| 取 key | `get_user_api_key(username)` | **不取**：在读用户 key **之前**就分流到 DSH | 取，并写进**该用户自己的** DSH_HOME |
| 实际使用 | 该用户自己的 key | DSH 实例自身的凭据 = `~/.dsh/.credentials.yaml`（**操作者的一把**） | 该用户自己的 key |
| 未配 key 的用户 | 400 `api key unavailable` | **照常可玩，费用记在操作者头上** | 起不来实例，报"没有可用的模型 API Key" |

**成因（不变）**：DSH 的凭据存储是 **DSH_HOME 级**的，不是会话级。`ctx.credentials.resolve(ref)`
只吃密钥名、**没有会话/用户维度**；`session.create` 能选 preset、能选 model，但**给不了 key**。
所以"每用户一把 key"必然推导出**每用户一个 DSH_HOME**，与「每用户实例」是同一件事。

**第一段（已实现，`Relay/instances.py`）**：

1. 每用户一个 DSH_HOME（`DSH_USERS_DIR`，默认 `<仓库>/.dsh-users/<用户名>`，0700）
2. 该用户的 key 写进它自己的 `<home>/.credentials.yaml`（0600，读-改-写，不覆盖 DSH 自己写的记录）
3. 按该用户 `settings.json` 的 `model` 生成**每用户 patch**：一个 `dsh-llm-pi-ai` 路由
   （`api: openai-completions` + `baseURL` 取自 `.env` 的 `<PREFIX>_URL`，密钥只写引用名
   `apiKeyEnv: LPSD_USER_KEY`）+ `agent-default-model`
4. 生成中转 key 并**按用户名登记**（`dsh_instances.username`），中转据此路由到人
5. 按需拉起 `dsh --profile letsplaydnd --patch <每用户 patch> --host 127.0.0.1 --port 0 --no-open`，
   等到上线；`DSH_INSTANCE_AUTOSTART=0` 可关
6. 停止：`UserInstances.stop()`；进程跟踪写在 `<home>/instance.pid`，因此 **Flask 重启后仍收得掉**
   （内存里的进程表会丢，这是实测踩到的）。认领 pid 前核对命令行里是否带着该用户的 home，
   **认不出来就不杀**（失败关闭），避免 pid 复用后误杀

**已实测**（伪造用户 + 一把**无效** key 跑通全程）：

| 检查 | 结果 |
|---|---|
| 起实例 | 7.6 秒上线，`instance_for_user('e2euser')` = 它的 instance_id |
| 用的是谁的 key | 请求上下文 `provider: letsplaydnd-user / model: qwen3.7-plus`，LLM 返回 **401 Incorrect API key** → 用的是**该用户的假 key**，不是操作者那把有效的 key |
| 凭据文件 | 只有 `refs.LPSD_USER_KEY = <该用户的 key>`，没有操作者的任何东西 |
| 停止 | 跨 Flask 重启仍能停掉进程，并撤销该用户名下的中转 key |
| pid 复用安全性 | `foreign`（命令行不是我们的）→ 拒绝发信号并丢弃陈旧文件；`unverified`（认不出）→ 拒绝并保留文件；`dead` → 清理文件 |

**第二段（上线前）**：

| 项 | 说明 |
|---|---|
| 独立 OS 账号 | `update.md` §1.1 的方向：`dsh-<用户名>` + `0700` home + `0600` 凭据。现在每用户只是**目录**隔离，跑在同一个进程用户下 |
| **回环租户隔离** | 所有实例都在 `127.0.0.1`，而 DSH 的特权接口按"Host 头是不是回环"放行。**当前可行的前提是本预设内没有可执行代码**（无 shell / web）——租户发起不了"伪造 Host 直连别人端口"这类攻击，与 P5-1 是同一条不变量。一旦引入任何代码执行工具，这条必须同时补上（`update.md` §1.3.1 的做法：iptables OUTPUT 按 `dsh-<name>` 限制） |
| 安装树完整性 | 所有租户实例共享同一份 DSH 代码树，任何 group/other 可写点都是跨租户注入点 |
| systemd 单元 | 目前由 Flask 拉起子进程。`update.md` §1.4 记了一条：systemd 命名空间只在由 systemd 拉起时生效 |
| 空闲回收 | 现在实例起来就不主动停（只有 `stop()`）。要不要按空闲时间回收，看内存实测 |

**两条禁令（不变）**：

1. 不可只做"没 key 就拒绝开始游戏"的门禁。那只做了一半：强制用户配 key，实际仍用操作者的 key 跑，**比现状更误导**。
2. **半成品不得部署。** 第一段完成前，任何登录用户都能消耗操作者的额度。

**与 P5-1 的关系**：补齐之后，每个实例的 key 落在**它自己的 DSH_HOME** 内，
而那是典型的"进程必须持有、模型因此也读得到"的一类文件——P5-1 读白名单是唯一挡得住它的东西。
两者一起上：只做隔离没有白名单，等于每个实例都能把自己的 key 念出来。

**本地测试不受此限**：本机是同一操作者，共用一把 key 无影响。

