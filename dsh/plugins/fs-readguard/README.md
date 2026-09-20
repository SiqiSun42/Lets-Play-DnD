# dsh-fs-readguard

LetsPlayDnD 的**模型文件读取白名单**：让 `read` / `read_image` 只能读会话工作区
与显式配置的根，其余路径一律拒绝。设计依据见 `spec.md` 的 **P5-1**。

## 为什么需要它

DSH 的沙箱（`dsh-sandbox` / `dsh-fs-sandbox`）**只管写**。官方 README 的原话是
「限制模型对文件的写入与编辑，**同时保留本地文件系统的读取行为**」——三个模式
（`read-only` / `workspace-write` / `danger-full-access`）都是关于写的，
`read-only` 的意思是"拒绝写"，不是"拒绝读"。DSH 任何一层都没有读路径规则。

所以模型可以 `read /opt/letsplaydnd/.env`、`read ~/.dsh/.credentials.yaml`、
`read /proc/self/environ`。本插件补上这条缺失的规则。

## 为什么是白名单

黑名单和白名单的实现成本**完全相同**：同一个检查点、同一段代码，只是比较方向反过来。
差别只在失败模式：

| | 失败模式 |
|---|---|
| 黑名单 | 出现一个未列入的新秘密文件 → **静默 + 灾难**；且要求穷举"现在和未来所有秘密" |
| 白名单 | 模型读不到某个正当文件 → **吵闹 + 无害**（模型报告读不到，加一个根即可） |

白名单只需枚举**我们自己的**目录，不需要枚举秘密。

## 它挡的是什么，不挡什么

- **挡**：模型被提示注入误导——游戏内容或玩家输入里夹带指令，诱导它去读密钥再念出来。
  模型没有 shell、没有网络，泄露渠道只有自己的文本输出、写入存档、以及 MCP 工具参数。
- **不挡**：攻击者在 DSH 进程内取得代码执行。那种情况下只有容器 / 微虚拟机有用。

## ⚠️ 不变量（硬性前提）

> **本预设不得引入任何可执行代码的工具**（bash / pwsh / 带 shell 的 subagent / 等价物）。
> 引入即等于同时拆除本插件。

理由：本插件是**可信代码中的策略，不是内核边界**。它成立的前提是"模型只能发工具调用、
没有第二条通往文件系统的路"。没有 shell，`read` 就是唯一的读路径，路径级围栏才完备。
一旦模型能执行代码，它就能绕过工具层直接 `open()`，本插件**静默失效**。

内核级隔离（`dsh-bash-sandbox` 的 Landlock 等）是给"存在不可信代码"准备的——我们不引入，
所以不需要它。这个取舍记录在 `spec.md` P5-1「为什么不选 systemd」。

## 安装

插件必须能被 profile 的模块解析器找到，所以要装进 profile 的 `node_modules`：

```bash
cd <项目根>
export DSH_HOME=~/.dsh          # 见下：Python runtime 版 dsh 不会隐式使用 ~/.dsh
dsh plugin --profile letsplaydnd add ./dsh/plugins/fs-readguard
```

这会在 `~/.dsh/profiles/letsplaydnd/package.json` 里记一条本地依赖（`link:`，即符号链接，
所以仓库里改代码立即生效）。卸载：`dsh plugin --profile letsplaydnd remove dsh-fs-readguard`。

> **必须显式 `export DSH_HOME`。** 项目 `venv/bin/dsh` 是 **Python runtime** 版
> （`deepseek_harness_runtime`），它对 `DSH_HOME` 的策略是"必须显式给、绝不隐式用 `~/.dsh`"。
> 不设就会报 `the Python runtime command requires an explicit DSH_HOME`。
> 在 DSH 会话内执行时该变量已由 harness 设好，所以从会话里跑不会遇到这个问题——
> 但这恰恰意味着**换到普通终端会突然失败**。

> **在 DSH 会话内装会失败。** `pnpm` 要 chmod profile 里的 bin shim，而 profile 在工作区之外，
> `workspace-write` 沙箱会拒绝，报 `ERR_PNPM_CMD_SHIM_CHMOD` / `EPERM`。
> 请在普通终端执行，或一次性放宽沙箱。`dsh --dump-config` 同理——它会写 profile 的 `cordis.yml`。

## 挂载

在 preset 里（`dsh/agent-presets/letsplaydnd/agent.cordis.yml`）：

```yaml
- id: fs-readguard
  name: dsh-fs-readguard
  config:
    readRoots:
      - !!js process.env.DSH_SKILLS_DIR ?? (process.cwd() + '/Skills')
```

`readRoots` 是**额外的**读根。会话工作区（`agent.session.header.cwd`）总是自动放行的，
不需要在这里写——它由调用方（Flask）按用户设定，写死反而会圈错地方。

当前配置：工作区（`Account/<user>`）+ `Skills/`。
`Templates/` **刻意不在名单里**：模板由 Flask 侧在「开局」阶段复制成存档，模型没有读写必要。
以后若需要（例如自建人物时参考格式），加进 `readRoots` 即可。

## 管辖范围

| 工具 | 是否受管 | 说明 |
|---|---|---|
| `read` | ✅ | 路径参数 `file_path` |
| `read_image` | ✅ | 路径参数 `file_path` |
| `write` / `edit` | ❌ | 写围栏由 host 平面的 `sandbox-policy` 负责（可写根 = 会话 cwd），它还会给出升权提示。这里再拦一次只会产生两套冲突的报错 |
| `skill` | ❌ | 技能加载器自己读 `SKILL.md`，路径由我们配置，模型只能选技能名 |
| `mcp__*` | ❌ | 运行在 MCP 服务进程里，不是文件系统通道 |

守卫通过 `ctx.tools.guard()` 注册——它是**单调**的，跑在可扩展的 `tools/pre-execute`
waterfall 之后，只能拒绝、不能放行，因此监听器顺序无法把拒绝翻回允许。

## 失败关闭

拿不到会话 cwd（`agent.session.header.cwd`）时**拒绝**而不是放行。
放行是静默失败，拒绝是吵闹失败——安全控制该有后者。

## 测试

```bash
node dsh/plugins/fs-readguard/test.mjs
```

不启动 DSH，直接喂假的 exec 对象。重点覆盖"它能不能拒绝"：
路径穿越、符号链接、前缀陷阱（`alice` 不能读 `alice-other`）这三类
看着像在里面、实际在外面的写法。

## 零依赖

不 import 任何 `@deepseek-ai/*` 包：本插件装在 profile 的 `node_modules` 里，
那里解析不到 dsh 安装目录下的包。路径规范化用纯 `node:fs` 实现。

## 已知边界

- 这是**策略而非内核边界**（见上「不变量」）。
- 不做"检查后、`open` 前"的 TOCTOU 收窄。模型无法制造符号链接（没有 shell，
  `write` 只写文本内容），而**已存在**的符号链接会被 `realpath` 穿透，所以
  这条竞态在本文的威胁模型下不成立。
