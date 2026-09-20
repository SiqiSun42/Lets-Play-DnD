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
    consult-zh/
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

- 位置：`Skills/consult-zh/`
- 结构：`SKILL.md` 加 `references/` 子树
- `references/` 下文件**不自动进入上下文**，由模型通过 `read` 获取；SKILL.md 正文须给出资源路径指引
- 语言隔离：中文与英文为独立目录（`consult-zh/`、`consult-en/`），不在同一 `SKILL.md` 内做语言分支

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

### P1 MCP 服务

**内容**：实现 `MCP/mcp_server.py`（两个工具）与 systemd 单元。

**验收**：两个工具可经 MCP 调用；进程常驻；RAG 仅加载一次。

**依赖**：无。

### P2 consult skills

**内容**：编写 `Skills/consult-zh/`，迁移 `Prompts/consult/` 内容至 `references/`。

**验收**：本地 DSH 完成「判断 → 检索 → 输出」，规则引用正确。

**依赖**：P1。

### P3 DSH profile

**内容**：编写 `dsh/profile.patch.yml`，基于 web-capable profile，加入 `dsh2server`。

**验收**：

- 模型可见工具恰为 `read` / `write` / `edit` / `skill` / `mcp__*`
- 工作区外写入返回拒绝
- 沙箱模式不可由模型自行提升
- 模型在极简工具面下完成一次三段流程

**依赖**：P1、P2。

### P4 中转服务器

**内容**：在 Flask 侧实现 `dsh2server` 协议 v1 服务端，覆盖规范 §12 的必做清单；实现实例注册、事件接收与转发、操作下发。

**验收**：

- 一个 DSH 实例能连接并出现在实例表中
- `session/assistant-stream` 的 `reasoning-delta` 与 `text-delta` 能实时转发到前端，打字机效果与迁移前一致
- 下发 `session.prompt` 能驱动会话并收到完整回复
- 断线后能自动重连并按 `seq` 补发，不丢事件

**依赖**：P3。

**起点**：移植 `php/dsh-relay.php` 或对照 `examples/server.js`。

### P5 安全加固

**内容**：

1. 每用户 DSH 实例的 systemd 文件系统命名空间隔离
2. 存档快照（工作区外裸库）
3. 中转服务器的 key 白名单与恒时比较
4. 回环租户隔离（多实例部署时）

**验收**：DSH 进程内不可读 `.env` 与 `account.db`；存档可回滚至任意回合。

**依赖**：P4。

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

- 无 approver 时沙箱提权是否失败关闭（P3）
- 模型在极简工具面下能否稳定完成三段流程（P3）
- `dsh2server` 在自定义 web-capable profile 下的能力集合是否满足需求（P3）
