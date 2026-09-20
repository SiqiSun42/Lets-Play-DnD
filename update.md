# LetsPlayDnD × DSH 迁移调研记录

> **状态**：讨论中，逐模块推进。
> **性质**：过程记录 / 决策台账，不是最终方案。所有模块过完后另写正式 spec。
> **备份基点**：`main` @ `00cbb7f`（2026-09-14 "prompt small change"，工作区干净）

---

## 目录

- [0. 总体目标](#0-总体目标)
- [1. 模块一：前端 + Account](#1-模块一前端--account)
- [2. 模块二：RAG](#2-模块二rag)
- [3. 模块三：提示词 + 工具](#3-模块三提示词--工具)
- [4. 模块四：Agent 流程](#4-模块四agent-流程)
- [5. 重点一：极简模式可行](#5-重点一极简模式可行)
- [6. 重点二：读约束问题](#6-重点二读约束问题)
- [7. 待办与进度](#7-待办与进度)

---

## 0. 总体目标

用手搓 agent 系统 → 改为借用现成 harness（DSH）：

1. 提示词 → skills
2. 工具 → 插件 / MCP server
3. 现有前端（Flask + 原生 JS）尽量不动，只换与 agent 的接口
4. Agent 流程放弃现有硬编码逻辑，改由 DSH 自行判断

---

## 1. 模块一：前端 + Account

### 1.1 前端接入方式：可行，且是 DSH 的设计意图

DSH 内核是一棵 Cordis 插件树，`profile` 决定挂哪个"应用壳"。自带 profile：
`web` / `headless` / `acp` / `sdk` / `sdk-minimal` / `tui`。

三条接入路径：

| 路径 | 启动方式 | 能拿到什么 | 评价 |
|---|---|---|---|
| **ACP** | `dsh --profile acp` | `agent_message_chunk`、`agent_thought_chunk`、`tool_call`、`tool_call_update` | 跨框架标准（agentclientprotocol.com）。刻意不给 DSH 特有呈现（plan/todo/terminal/elicitation），无 `session/load`/fork/回放 |
| **SDK** | `dsh --profile sdk` | `session.event`（**运行时内每个会话、不过滤**）、`session.status`、`subagent.started/finished` | **推荐**。信息最全，官方有 Python SDK |
| web host `/api` | `dsh --profile web` | Typert RPC + `/api/remote.mux` WebSocket | 内部 API，需 `dsh-client-*` 生成的编解码器，版本升级易崩，**不建议** |

**前端改动量评估**：现有链路已是 SSE，前端已有解析能力，大概率**一行不用改**。

- 后端：`server.py:799` `POST /api/consult/message/stream` → SSE `data: {json}\n\n`
- 前端：`UI/js/chat-view.js:655` 用 `fetch` + `res.body.getReader()` 手动解析 SSE
- 已有分支：`thinking`(683) / `content`(693) / `end_bubble|new_bubble`(690) / `done`(702) / `error`(717)
- 已有渲染：`createReasoningBlock()`(483)

→ 只需把 SSE 的**生产者**从 `System/consult/consult.py` 换成"读 DSH `session.event` 再翻译成同样的事件 JSON"。

### 1.2 多用户各自 API Key（BYOK）：DSH 原生不支持

**证据（已逐条核实）**：

- `ctx.credentials.resolve(ref)` 签名只吃密钥名，**无会话/用户维度**（`dsh-credentials/lib/types/index.d.ts:129`）
- `dsh-llm-deepseek` 的 `apiKeyEnv` 是**组合期静态配置**，默认 `DEEPSEEK_API_KEY`；`resolveApiKey` 每请求都调，但解析的永远是同一个名字（`dsh-llm-deepseek/lib/index.js:1881, 2038-2048`）
- `dsh-credentials-local` 落地为 `~/.dsh/.credentials.yaml` 单文件
- SDK `initialize` 与 ACP `session/new` 均**没有 key 字段**
- ⚠️ 适配器里的 `userId` 是 `getOrCreateAnonymousUserId()`（header `x-deepseek-harness-user-id`），**匿名遥测 ID，不是租户**

**扩展点存在**：`GenerateOptions` 携带 `sessionId`（`dsh-llm/lib/types/types.d.ts:437`，注释："Session identity stamped by the loop for request routing"），而 `LlmAdapter.stream(options)` 是唯一必须实现的方法 → 可以写自定义 adapter 按 sessionId 路由到不同 key。

**生态现状**：三个相关项目**全部选择 per-user instance**，无一采用"单实例多用户"：

| 项目 | 做法 | 是否 BYOK |
|---|---|---|
| [dsh-server-deployment](https://github.com/AnkoCD/dsh-server-deployment) | 多用户门户 + 每用户独立 DSH 实例 + OS 级隔离 | ✅ **每用户独立 API Key**，有成品 |
| [dsh-ui-auth](https://github.com/0QwQ0/dsh-ui-auth) | 单实例 + 多用户认证网关 | ❌ 模型/Key **仅管理员**，普通用户 403 |
| [aiworkskills/deepseek-harness-server](https://github.com/aiworkskills/deepseek-harness-server) | `@dshserver/*`，每用户独立 Runtime + OAuth 委托 | 管的是业务工具授权 |

`dsh-ui-auth` README 自述："DSH 本身按单用户设计……多租户级别的强隔离需要 DSH 侧的支持。"

**初步方案**：**采用每用户一 DSH 实例**，不写自定义 adapter。
参考 `dsh-server-deployment` 的 `gateway/userctl.js` 与 `docs/multi-user-isolation.md`——那是现成的、经安全加固的实现（独立 OS 账号 `dsh-<name>`、`0700` home、`0600` 凭据、systemd 资源限制）。

**映射到本项目的形态**：

```
你的前端 (UI/)  →  现有 SSE  →  Flask（当网关 + 实例管理）  →  每用户一个 DSH 子进程
                                                              (独立 DSH_HOME + key + 端口)
```

`account.db` 的用户名天然对应 `dsh-<name>` / 独立 `DSH_HOME`。

### 1.3 两个安全坑（dsh-server-deployment 踩过）

1. **回环租户隔离**：所有实例同处 `127.0.0.1`，而 DSH 特权接口按"Host 头是否回环"放行 → **任何租户的 agent 都能伪造 Host 直连他人端口窃取 API Key**。其解法：iptables OUTPUT 链，每个 `dsh-<name>` 只能连自己的实例端口。
2. **安装树完整性**：所有租户实例**共享执行**同一份 DSH 代码树，任何 group/other 可写点都是跨租户注入点。部署后须自检 `find <树> -not -path '*/users*' -perm /022 | wc -l` 输出 0。

### 1.4 部署走法 —— 已定

**写围栏用 DSH，读隔离用 systemd。各管各的层。**

```ini
# DSH 实例的 systemd 单元
InaccessiblePaths=/opt/letsplaydnd/.env
InaccessiblePaths=/opt/letsplaydnd/account.db
ProtectHome=yes
ProtectProc=invisible
ProcSubset=pid
ReadOnlyPaths=/opt/letsplaydnd
NoNewPrivileges=yes
```

要点：

- 不写 path-guard 插件（除非以后要把安全打包进 profile 跨平台复用）
- 原先的 A/B 二选一被这个组合取代：**不建独立 OS 账号**，改用 systemd 的文件系统命名空间
- `ProtectProc=invisible` + `ProcSubset=pid` 是必需的——否则同账号下 DSH 仍可读 `/proc/<flask_pid>/environ` 拿到密钥
- `NoNewPrivileges=yes` 在本设计里可以开（DSH 不需要 sudo）。注意 dsh-server-deployment **不能**开，因为它靠 sudo 调文件助手——两者设计不同
- `ProtectProc` / `ProcSubset` 需要较新的 systemd，部署前先确认版本

---

## 2. 模块二：RAG

**结论**：**独立 Python 服务 + Streamable HTTP MCP**，直接 `import` 现有 `RAG/` 与 `Dice/`。不进 Flask，不发布，不版本化。

### 2.1 "包装成插件" vs "暴露成工具"

两件事要拆开：

- ❌ **包装 / 发布**：发 npm 包或独立版本化的 artifact → 版本漂移风险（RAG 更新了插件没更新就错位）。**拒绝，判断正确。**
- ✅ **暴露成工具**：模型要能调用 `search_rules`，就必须以工具形式出现在 DSH 里——这是 DSH 唯一的调用通道。

关键：**"是工具" ≠ "是发布物"**。MCP server 只是 repo 里的一个脚本，`import` 的就是现有模块。**RAG 与 adapter 在同一次 commit 里改，物理上不可能错位。**

### 2.2 为什么是 HTTP 而不是 stdio（模块一 × 模块二的交叉）

定了「每用户一个 DSH 实例」之后：

| MCP 形态 | 结果 |
|---|---|
| **stdio**（DSH spawn 子进程） | 每实例 spawn 自己的 server → **N 份 Chroma + N 份 embedding 模型** |
| **Streamable HTTP**（连同一个 URL） | 所有实例连同一 server → **1 份** |

现有 Flask 进程里 RAG 是**懒加载但共享**的（README："`consult` 在真正检索时才 `import RAG`，避免打开咨询页就加载 embedding"）。改 stdio 就是从 1 份变 N 份——**是回退**。`bge-small` 量级几百 MB/进程，10 并发就是几个 GB。

→ **选 HTTP MCP。理由是内存，不是延迟**（localhost 那一跳亚毫秒）。

### 2.3 三个候选被否掉的原因

| 方案 | 否掉的理由 |
|---|---|
| stdio MCP | 每 DSH 实例一份 RAG 模型，内存 N 倍 |
| 挂 Flask 暴露 MCP endpoint | 可用，但 DSH 与 Flask 互相耦合 |
| DSH Node 插件 | 要把 Chroma + sentence-transformers 重写到 Node → 不可行 |

### 2.4 骰子

`Dice/dice.py` 仅 21 行 `random.randint`，无状态、无依赖、无耦合问题 → **跟着 `search_rules` 放同一个 server**，不单独决定。

### 2.5 落点

> 一个独立 Python 进程（`mcp_server.py` + systemd），暴露 `search_rules` 与 `roll_dice` 两个 MCP 工具，直接 import 现有 `RAG/` 与 `Dice/`。与 Flask 平级。

---

## 3. 模块三：提示词 + 工具

### 现状

- `Prompts/prompts.py:5` `_read_prompt()` 启动时把全部 md 读成模块级常量（14-40）
- **纯字符串，无模板变量替换**（已 grep 确认无 `.format` / 占位符）
- 拼接靠各 `System/*.py` 手写 messages 列表
- 编号文件是**阶段列表**而非状态机：`1.classify` → `2.prepare` → `3.x`（按类别五选一）→ `4.x` 更新
- `Skills/` 仅 `rag-query/SKILL.md` 一个雏形；`System/consult/consult.py:333-462` 有一段**被注释掉的** `run_stream`，演示 `invoke_skill` 三段式，**现网未启用**

### 已有对应物

| 本项目 | DSH |
|---|---|
| `Skills/rag-query/SKILL.md` | `dsh-skill-filesystem`：目录式 `<name>/SKILL.md`，YAML frontmatter 必填 `name`/`description`，可选 `whenToUse`、`disable-model-invocation`、`user-invocable`；**支持热加载** |
| `Prompts/*.md` | 同上，或写进 agent preset 的 system prompt |
| `Tools/*/*.py` 的 schema dict | `dsh-tool-*` 插件 / MCP 工具 |

> ✅ **好消息**：因为 prompt 无模板变量、自包含，搬进 `SKILL.md` 是**机械操作**，只需补 frontmatter。

> ⚠️ **坑**：`dsh-skill-filesystem` **刻意不支持**递归发现 `**/SKILL.md`，只扫根目录下的目录 bundle 或平铺 `.md`。现有 `Skills/rag-query/SKILL.md` 正好合规。

### 3.1 工具审计：19 个工具里只有 2 个是真能力

| 类别 | 数量 | 处置 |
|---|---|---|
| **A 结构化输出壳**（无副作用） | 10 | agent 化后**全部消失** |
| **B DSH 直接覆盖** | 2 | `fetch_panel_file`→`read`；MCP `edit_file`/`write_file`→`write`/`edit` |
| **C 真能力** | 2 | `search_rules`、`roll_dice` → 保留（MCP） |

A 类清单：`classify_turn`、`narrate_opening`、`narrate_result`、`dm_note`、`calculation_step`(×2)、`plan_panel_update`，以及 battle 侧同类。

它们存在的唯一理由是**逼 LLM 输出结构化数据**，因为下游 Python DAG 要按类型分支。agent loop 下模型直接写正文，壳就没有存在意义。

### 3.2 skill 目录结构：resources 可用，但是"指引"不是"附件"

`dsh-skill-filesystem` 承认 bundle 资源：`references`、`scripts`、`assets` **等**子树，且监视器**故意忽略**资源子树的变更。`dsh-skill-badge` 是现成范例（把 `assets/` 作为资源基底公开）。

**但** `dsh-tool-skill` 原文：

> **资源是指引，而非附件**——工具报告基础目录/URL/不透明提示，**但既不列举也不为模型获取引用文件**

即：`skill` 工具只给模型**正文 + 资源根指针**，资源文件**不会自动进上下文**，模型得自己再 `read`。

→ 结构成立（与设想一致）：

```
Skills/
  consult/
    SKILL.md            ← 正文：流程总纲 + 指向资源
    references/
      opening.md        ← 现在的提示词
      judge.md
      polish.md
```

### 3.3 三种摆法的取舍

| 结构 | 模型步数 | 上下文 | 适合 |
|---|---|---|---|
| **A** 一 skill + 资源子目录 | 1 次 `skill` + N 次 `read` | 按需 | 阶段共享总纲、想按需取 |
| **B** 多个**兄弟** skill | 每次 1 次 `skill` | 只加载用到的 | 阶段彼此独立 |
| **C** 一 skill、提示词全内联 | 1 次 `skill` | 全量 | 延迟最低，上下文最重 |

补充：A 的 N 次 `read` 可**并行**（`read` 并发安全）；consult 三段在同一回合内连续走完，所以"按需"的价值不大 → 若提示词不长，**C 最实在**。

### 3.4 已闭合

**skill = 模型自主调用**（挂 `dsh-tool-skill`）。这是"只有 read/write"之外的第 3 个工具，属于"你提供的插件"，可接受。

产出：流程写进 `SKILL.md`，现有提示词放进 `references/`。

**遗留**：语言分派，见 §4.4。

---

## 4. 模块四：Agent 流程

### 现状：不是 agent loop，是固定 DAG

`System/game/game_zh.py:799` `run_game_zh()`：

```
软锁检查(809)
  → 若 battle_status.json 的 is_battle/ending_phase → 转 battle_stream_zh.py:70(825)
  → 取 history[-20:](832) + load_game_data(67) + panel_dir_listing(game.py:198)
  → _classify_and_prepare(255)  ← asyncio 并发跑 classify(116) 与 prepare(163)
  → _build_generate_messages(283) 按类别选 CATEGORY_PROMPTS(58) → 生成(861-882)
  → append_message(890) → _apply_panel_updates(737)
```

- 每个 stage 一次 LLM 调用，失败重试 `MAX_ATTEMPTS=3`
- stage 顺序**硬编码在 Python 里**
- 工具是 OpenAI function schema 的纯 dict 列表，**不自动执行**，靠手写 `if func_name == ...` 分发（`game_zh.py:183-211`、`_parse_narrate_tools` 304）
- 真正的循环只出现在战斗：`System/battle/battle_loop_zh.py:265` `run_battle_loop()`，`for _ in range(64)`(304) 按先攻推进
- 现有工具：`classify_turn`、`roll_dice`、`search_rules`、`fetch_panel_file`、`narrate_opening`/`calculation_step`/`narrate_result`/`dm_note`、`plan_panel_update`、文件写入走 MCP filesystem server

### ⚠️ 关键取舍：agent 化可能**更慢**

`_classify_and_prepare` 用 asyncio **并发**跑 `classify` 和 `prepare`——一次往返拿两个结果。

自由 agent loop 下，模型得先调 `classify_turn`、看结果、再决定下一步 → **天然串行**。常规回合可能从「1 次并发往返」退化成「2-3 次串行往返」。

**初步方案：混合架构**
- 固定且可并行的 stage（`classify` / `prepare`）**留在 Python** 继续当 DAG 跑
- 只把**真正需要临场决策**的部分（叙事、战斗策略）交给 agent loop
- 确定性部分（骰子、战斗先攻、状态落盘）留在 Python 工具里当唯一真源

**battle 暂缓**——该流程用户尚未完成。

### 4.1 修正：agent 化不一定更慢

上一轮的判断需要修正。现在是 `classify` ‖ `prepare`（1 次往返）→ `generate`（1 次往返）= **2 次往返**。

Agent 化后，若模型在**一次生成**里把事情想清楚，就是 **1 次往返**；若需读面板文件，则 `read`(1) + `generate`(1) = 2 次，**持平**。

→ **真正的损失不是速度，是控制力**（见 4.2、4.3）。

### 4.2 按类别分派提示词的控制权转移

现在 Python 按 `classify` 结果从 `CATEGORY_PROMPTS` 五选一（3.0–3.4）。agent 化后这变成**模型自己决定读哪个文件**：

- 风险：读错类别、或把几类都读了
- 是否接受？若接受，SKILL 正文要明确"按类别读对应 references"

### 4.3 ⚠️ 存档写入安全（最重要，"有问题再约束"在这里不成立）

现在是 **plan → validate → apply**：`plan_panel_update` 输出 5 个 bool → `parse_update_plan` 解析 → `_apply_panel_updates` 执行。**模型改不了存档，只能声明意图。**

agent 化后模型直接 `write` → 失去拦截点。而**坏写入直接损坏存档，"事后约束"来不及**。

对策（建议组合）：

1. **每个存档目录 git 化**，每回合 commit → 任何坏写入可回滚。最便宜，且完全符合"有问题再约束"的哲学
2. `dsh-fs-observation-policy`（读后写）：防止没读就覆盖
3. 保留一个 `plan_panel_update` 式 gate 工具（与 §3.1"壳全部消失"冲突，需权衡）

### 4.3 决策

**采用快照 + 读后写，不保留 gate 工具。**

```bash
# 由 Flask 在每回合结束后执行
git --git-dir=/var/lib/letsplaydnd/history/<save_id>.git \
    --work-tree=Account/<user>/Saves/<id> add -A
git --git-dir=/var/lib/letsplaydnd/history/<save_id>.git \
    commit -m "turn N"
```

⚠️ **快照仓库必须放在模型够不到的地方。** 若在存档目录内 `git init`，模型拥有工作区写权限，理论上能写坏 `.git/`（尤其被 prompt injection 引导时）。所以用**工作区之外的裸库**。

配合 `dsh-fs-observation-policy`（读后写）。

**不保留 `plan_panel_update`**：你的哲学是"有问题再约束"，快照就是那个约束。留着它会把 §3.1 想消掉的结构化输出壳请回来。

### 4.4 中英双语分派 —— 已决定**暂缓**

**决策**：暂不做双语。先把中文流程跑通、测试完整后再写英文。理由：否则一份提示词要改两份，迭代期维护成本翻倍。

**唯一需要注意的结构约束**：**别把两种语言混进同一个 `SKILL.md`**。不要写"如果是英文则……"的分支——那正是"改一份要改两处"的来源。zh 与 en 应在**文件层面完全分开**：

```
Skills/
  consult-zh/SKILL.md + references/
  consult-en/SKILL.md + references/     ← 以后新增，不碰中文那份
```

加英文 = 纯新增文件，中文那份一行不动。

> 现有代码已经是这个模式：`System/game/game_zh.py` 与 `game_en.py` 是两份独立文件，不在同一份里做语言分支。把同样的隔离带到 skill 层即可。

**遗留的技术问题（到时再解）**：skill 是部署级静态配置，而语言是存档级（`in_game_language` 创建时锁定）→ 需要 agent preset 或会话注入来分派。

---

## 5. 重点一：极简模式可行

**需求**：只有 `read` / `write`，只能用我提供的插件，不需要 subagent / workflow 之类。

### ⚠️ 先避坑：`sdk-minimal` 名字像但**不是**你要的

`dsh-sdk-minimal` 自述："刻意排除 `dsh-base`、Web、settings、托管凭据、遥测、compaction、**文件系统工具**、workspace 指令、skills、jobs 与 subagent"，"其 `danger-full-access` 策略允许 shell 修改进程可访问的任何路径"。

看它的 `cordis.patch.yml`：**只挂一个持久 shell，没有 read/write 工具，全权限**。它是"极简**编程** agent"，不是"极简**文件** agent"。按名字选会走错路。

### 正确做法：自定义 profile

DSH 是"everything is a plugin"——**一个工具存在，仅仅因为你挂载了它的那一行**。

完整 profile（`dsh-base`）默认挂 13 个工具包：
`tool-bash`、`tool-pwsh`、`tool-jobs`、`tool-fs`、`tool-fs-search`、`tool-skill`、`tool-subagent`、`tool-subagent-control`、`tool-workflow`、`tool-todo`、`tool-goal`、`tool-ralph`、`tool-web`

**模板**：`dsh-sdk-minimal/cordis.patch.yml` 是一棵**完全独立、不继承 base** 的配置树，结构清晰，把工具行换掉即可。

```yaml
- insert:
    # ... llm / session / agent / system-prompt 等必需内核（照抄 sdk-minimal）

    - id: tool-fs
      name: '@deepseek-ai/dsh-tool-fs'   # read / read_image / write / edit

    # ... 你自己的插件（RAG MCP、骰子等）

    # 全部不挂：bash / pwsh / jobs / fs-search / skill /
    #          subagent / workflow / todo / goal / ralph / web
```

### 两层独立管控

1. **profile 层**：根本不挂 = 不存在
2. **注册表层**：`ctx.tools.restrict(filter: ToolRestriction)`，`{ allow?: string[], deny?: string[] }`，`allow` 是"只保留"，两者**取交集**；且是 **per-agent scope** 的

另有 dispatch 前的 `allow / deny / ask` 钩子；社区插件 [`dsh-tool-policy`](https://github.com/Drifter-yh/dsh-tool-policy)（"Declarative default-deny tool policy"）包的就是这个。

### 写围栏：`dsh-sandbox-policy` + `dsh-fs-sandbox`

⚠️ **`dsh-fs-local` 不做路径隔离**——原文："`config.cwd` 只是解析默认值，**不是约束边界**：绝对路径与 `..` 都可以逃逸它"。

```yaml
- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
- id: fs
  name: '@deepseek-ai/dsh-fs-sandbox'
  config:
    cwd: /path/to/Account/<user>/Saves/<save_id>   # ← 围栏在这里
- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
```

| 模式 | 行为 |
|---|---|
| `read-only` | 拒绝所有变更（**故障安全默认值**） |
| `workspace-write` | 只允许写会话工作区或平台临时根目录 |
| `danger-full-access` | 不限制 |

越界返回 `FS_SANDBOX_DENIED`。

**可选项**：`dsh-fs-observation-policy`（读后写策略）——要求先读才能覆盖/编辑，且文件被外部改过会拒绝并提示重读。适合"存档不能被并发写坏"。

---

## 6. 重点二：读约束问题

### DSH 内置沙箱**只管写**

`dsh-sandbox-local` 是真·内核级沙箱（Linux bwrap/Landlock、macOS Seatbelt、Windows ACL 受限令牌），但设计是写围栏：

- bwrap profile："**只读宿主根目录**、全新 `/dev` 与私有 PID 命名空间中的 `/proc`" → 全盘可读
- Seatbelt profile："**默认允许**，带 `(deny file-write*)`"
- `dsh-fs-sandbox`："限制模型对文件的**写入与编辑**，**同时保留本地文件系统的读取行为**"

| | DSH 内置沙箱管不管 |
|---|---|
| 写 | ✅ 严格围栏 |
| **读** | ❌ **故意全开** |

### 但分派层有钩子（这是关键）

`dsh-tools` 提供执行前策略：

```ts
'tools/pre-execute'   // waterfall 监听器
// exec = "the pending call (name, parsed arguments, caller agent)"
// 返回 PreToolDecision = allow | deny(reason) | ask

export type ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined;
// "A monotonic execution guard evaluated after every 'tools/pre-execute'
//  listener and before the tool body. Returning a reason denies the call."
```

**解析后的参数（含 `path`）在守卫里可见** → 可写出路径级读围栏。

关键性质：**"listener ordering cannot turn a denial back into permission"**——守卫单调，一旦 deny，没有后续 listener 能翻回 allow。这正是硬安全围栏需要的。

⚠️ **前提**：守卫能管住**工具调用**，管不住**进程能做的事**。所以它**只在无 shell 时完备**——`read` 是唯一读路径。若有 bash，挡不住 `cat /etc/passwd`。

> 💡 本项目"极简模式"的设计，恰好让工具级读围栏成为**充分条件**。

### 为什么本项目必须管读

(1) `server.py` 的 `_fernet()`：

```python
def _fernet():
    raw = app.secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(raw.ljust(32, b"0")[:32])
    return Fernet(key)
```

Fernet 密钥**从 `FLASK_SECRET_KEY` 直接派生**，而该值明文在 `.env`，`account.db` 在旁边。

(2) 因此只挂 `read` 即可完成：

```
read .env  →  FLASK_SECRET_KEY
           →  (a) 伪造任意用户 Flask session cookie，含 admin   ← 不需解密，全站接管
           →  (b) 配合 account.db 解密所有人的 api_key_enc
           →  同时拿到 RESEND_API_KEY
```

（Flask 用 `secret_key` 签名 session cookie，而鉴权就是 `session.get("username")`。）

(3) **同 OS 账号下无隔离**，连 `/proc/<flask_pid>/environ` 都能读——所以"把密钥改成环境变量"也挡不住。

### 三个初步方案（成本低 → 高）

| # | 方案 | 读约束 | 成本 |
|---|---|---|---|
| ① | 接受读开放，只做写围栏（`workspace-write`） | ❌ | 零。需**明示接受**上述风险 |
| ② | 写 path-guard 插件（挂 `tools/pre-execute`） | ✅ 无 shell 下完备 | 几十行 Node；需处理路径规范化（`..`、符号链接） |
| ③ | systemd 加固 / 容器 | ✅ 内核级，DSH 也绕不过 | 零代码，声明式 |

方案 ③ 示例（Ubuntu VM）：

```ini
InaccessiblePaths=/opt/letsplaydnd/.env
InaccessiblePaths=/opt/letsplaydnd/account.db
ProtectHome=yes
ReadOnlyPaths=/opt/letsplaydnd
```

**建议**：**③ 为主，① 打底**。写围栏用 DSH 的 `workspace-write`（agent 行为约束该 DSH 管），读隔离用 systemd（进程边界该 OS 管），各管各的层。② 仅在想要"可移植的安全"打包进 profile 时才值得写。

### 关于"换 harness 能否回避"

**不能**。这是结构性问题：**任何以你的 OS 用户身份运行的 agent，都能读你的用户能读的一切**（pi、Claude Code、Codex 同理）。差别只在策略层：

| | 读围栏在哪一层 |
|---|---|
| 有的 harness | 内置**路径级**权限规则（如 `Read(./secrets/**)` 可 deny） |
| 有的 harness | 完全不提供，只能靠 OS / 容器 |
| **DSH** | 内置沙箱只管写；但**分派守卫可编程**，能自己补上 |

> 结论：**不需要为了这个换框架。**

---

## 7. 待办与进度

- [x] 用户 git branch 备份当前可跑版本 → 基点 `main` @ `00cbb7f`（**待用户执行**）
- [x] 模块一（前端接入 + 多用户 key + 安全坑）讨论
- [x] 重点一：极简模式
- [x] 重点二：读约束
- [x] 模块一 1.4：部署走法 → **写围栏用 DSH，读隔离用 systemd 命名空间**
- [x] 模块二：RAG → 独立 Python 服务 + **HTTP** MCP
- [x] 模块三：skill = 模型自主调用
- [x] 模块四 4.2：按类别分派提示词 → 交给模型，在 SKILL 正文约束（"有问题再约束"成立）
- [x] 模块四 4.3：存档写入安全 → **快照（工作区外裸库）+ 读后写**，不保留 gate 工具
- [x] 模块四 4.4：中英双语 → **暂缓**（先跑通中文；结构上隔离两种语言，不混进同一 SKILL.md）
- [ ] 写正式 spec → 见 `spec.md`

---

## 附：DSH 关键事实速查

| 事项 | 结论 |
|---|---|
| 换前端 | ✅ 设计支持，profile 切换。推荐 `sdk`（Python SDK + `session.event` 不过滤） |
| 回复 + 思考上屏 | ✅ ACP 有 `agent_thought_chunk`；SDK 有 `session.event` |
| 每用户各自 key | ❌ 原生不支持。生态共识 = 每用户一实例 |
| 极简工具集 | ✅ 自定义 profile，只挂 `dsh-tool-fs` |
| 按名 allowlist | ✅ `ctx.tools.restrict({ allow })` |
| 写围栏 | ✅ `dsh-sandbox-policy` + `dsh-fs-sandbox`（默认 `read-only`，fail-closed） |
| 读围栏 | ⚠️ 内置沙箱**不管**；需 path-guard 插件（无 shell 下完备）或 OS/容器 |
| 沙箱失败姿态 | ✅ **fail-closed**（`SANDBOX_UNAVAILABLE`，不会无沙箱裸跑） |
| skills 格式 | 目录式 `<name>/SKILL.md`；**不支持**递归 `**/SKILL.md` |
| RAG 接法 | 独立 Python 服务 + **Streamable HTTP** MCP（理由是内存，非延迟），工具名 `mcp__<server>__<tool>` |
| skill 资源 | `references`/`scripts`/`assets` 等子树可用，但是**"指引"不是"附件"**——模型需自己 `read` |
| 真能力工具 | 19 个工具里只有 `search_rules` + `roll_dice` 需要保留 |
| MCP 传输 | `dsh-mcp-client` 支持 stdio 与 Streamable HTTP；本部署选 HTTP |
