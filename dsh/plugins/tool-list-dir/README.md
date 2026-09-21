# dsh-tool-list-dir

LetsPlayDnD 的**目录列举工具** `list_dir`：让模型看清工作目录里有哪些文件。
**根固定为会话工作目录，模型只能传相对路径**。设计依据见 `spec.md` 的 **P6 / §9.3.1**。

## 为什么需要它

`dsh-tool-fs` 只给四个工具：`read` / `read_image` / `write` / `edit`。`read` 喂目录会报
`FS_NOT_REGULAR_FILE`，DSH 也没有任何官方插件把"列目录"交给模型
（`dsh-tool-fs-search` 的 `glob` 能给路径，但它要额外挂 `ctx.subprocess` 去 spawn `rg`，
而且 `grep` 是**内容**通道——见下"为什么不选它"）。

而游戏流程的第一步就是"看清存档里有哪些文件"：地点文档是模型自己新建的，
文件名只有列出来才知道。

## 为什么根由系统给、路径由模型给

模型只传 `path`（例如 `"world"`），工作目录由插件从 `exec.agent.session.header.cwd` 取——
与 `dsh-tool-fs` 解析 `read` 相对路径时用的是同一个字段。这样：

- 模型不需要、也无法指定根，**别用户 / 别存档的文件名字都看不到**；
- 上界 = 会话 cwd，与 `fs-readguard` 的读白名单是同一个圈。

**MCP 工具做不到这一点。** MCP 服务只收到自己 schema 里声明的参数，拿不到会话上下文
（唯一的额外通道是那一行的静态 `headers`）。所以早先那版 MCP 工具只能是
`list_dir(base, path)`——让模型自己报工作目录，**模型报什么就信什么**，
顶多再用"必须在 `Account/` 之下 + 上溯到存档根"兜一层。工具在进程内注册就没有这个限制。
那一版已删除（`MCP/mcp_server.py` 现在只有 `search_rules` 与 `roll_dice`）。

## 围栏

两道，**都过才放行**（只查一道都会漏掉另一类）：

| 检查 | 挡住什么 |
|---|---|
| 词法：`displayPath` 是否在 cwd 之内 | `../../..` 这类上溯 |
| 真实：`targetKey`（realpath）是否在 `realpath(cwd)` 之内 | 工作目录里**已存在**的符号链接（`link -> /etc`） |

拿不到会话 cwd 时**失败关闭**（拒绝），与 `fs-readguard` 同一取舍。

它**不**读任何文件内容：`ctx.fs.listDir()` 只 stat（官方注释：`file contents are never read`），
所以即使围栏出 bug，泄露面也只有**文件名**，没有文件内容。这也是它比 `grep` 更小的原因。

## 为什么不选 `dsh-tool-fs-search`

官方那个插件提供 `glob` / `grep`，`glob` 的解析基准同样是会话 cwd——这一点它和我们一样。
不选它的理由有三条，任何一条单独看都不致命，合起来就不划算：

1. **它 spawn `rg` 子进程**，要额外挂 `dsh-subprocess-local`。那是**不受沙箱约束**的执行器
   （沙箱只管写、管的是 `ctx.shell`），工具面因此多出一整个后端；
2. **`grep` 返回文件内容行**。围栏一旦有洞，泄露的是内容而不只是文件名；
3. 我们要的只是"有哪些文件"。多两个工具、多一个后端，换来的能力本流程用不上。

## 工具定义是手写的（为什么不用 `defineTool`）

`ctx.tools.register()` 收的就是**裸 `ToolDefinition`**：`{ name, description, parameters, output: {schema, render}, execute }`。
`defineTool`（`@deepseek-ai/dsh-tools`）只是"入参 spec → JSON Schema + 校验 + render"的便利包装
（源码见 `dsh-mcp-client` 里 `createDefinition`：它本身就是手写的）。

而本插件以 `link:` 装进 profile，**真实路径仍在仓库里**，Node 从真实路径向上找 `node_modules`，
走不到 `~/.dsh/profiles/node_modules`，所以 `@deepseek-ai/*` 一律 import 不到（实测 `ERR_MODULE_NOT_FOUND`）。
详见 `dsh/plugins/fs-readguard/README.md`。

代价：**入参校验要自己做**（`defineTool` 白送的那层没有）。本工具只有一个可选字符串参数，
用 `typeof` 判就够了。工具名 `list_dir` 不与保留名 `run_code` 冲突。

## 安装

```bash
cd <项目根>
export DSH_HOME=~/.dsh
dsh plugin --profile letsplaydnd add ./dsh/plugins/tool-list-dir
```

`link:` 依赖，仓库里改代码立即生效。卸载：`dsh plugin --profile letsplaydnd remove dsh-tool-list-dir`。
（`DSH_HOME` 必须显式给、必须在普通终端跑，原因同 `fs-readguard` 的 README。）

## 挂载

`dsh/agent-presets/letsplaydnd/agent.cordis.yml`：

```yaml
- id: tool-list-dir
  name: dsh-tool-list-dir
```

`maxEntries` 可选（默认 200），限制一次最多列多少项。

## 输出

```
world/
  allies/
  渔村杂货铺.md
```

路径相对工作目录（工作目录本身显示成 `.`），可直接喂回 `read`。目录带尾斜杠，
点开头的项不显示，空目录显式写"（空）"，截断了会讲明。

## 测试

```bash
node dsh/plugins/tool-list-dir/test.mjs
```

不启动 DSH：用一个假 `ctx.fs` 模拟 `dsh-fs-local` 的解析语义
（`displayPath` = 词法解析、`targetKey` = realpath），在**真实的临时目录**上跑，
所以符号链接、`..` 上溯、点开头项这些边界是真在磁盘上验的。重点覆盖"它能不能拒绝"。

## 已知边界

- 与 `fs-readguard` 一样是**策略而非内核边界**：成立前提是预设内没有可执行代码。
  见 `fs-readguard` README 的「不变量」。
- `isInside` / `canonicalize` 与 `fs-readguard` 里是**两份实现**（插件各自自包含、零依赖是硬约束）。
  改动其中一份时请同步另一份，两份的测试都覆盖了前缀陷阱与符号链接。
- `link/..` 词法上塌回工作目录，因此是放行的——它列的就是工作目录本身，没有越界。
  真正去遍历磁盘才会走到外面，而我们不遍历：`ctx.fs.resolve` 是词法解析，列的是那个目录。
