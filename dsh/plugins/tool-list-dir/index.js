/**
 * LetsPlayDnD 的目录列举工具 `list_dir`（spec.md P6 / §9.3.1）。
 *
 * 它解决什么问题
 * --------------
 *
 * `dsh-tool-fs` 只给 read / read_image / write / edit 四个工具，`read` 喂目录会报
 * `FS_NOT_REGULAR_FILE`，**模型没有任何列目录的手段**。而游戏流程的第一步就是
 * "看清存档里有哪些文件"：地点文档是模型自己新建的，文件名只有列出来才知道。
 *
 * 为什么根由系统给、路径由模型给
 * -----------------------------
 *
 * 模型只传 `path`（例如 "world"），工作目录（存档的 data/）由本插件从
 * `exec.agent.session.header.cwd` 取——与 `dsh-tool-fs` 解析 `read` 的相对路径时
 * 用的是同一个字段。这样：
 *
 * - 模型不需要、也无法指定根，别用户/别存档的文件名字都看不到；
 * - 上界 = 会话 cwd，与 fs-readguard 的读白名单同一个圈。
 *
 * MCP 工具做不到这一点：它只收到自己 schema 里声明的参数，拿不到会话上下文，
 * 所以早先那版 `list_dir(base, path)` 只能让模型自己报工作目录——模型报什么就信什么。
 * 工具在进程内注册就没有这个限制。
 *
 * 为什么用 ctx.fs 而不是自己 node:fs
 * --------------------------------
 *
 * `ctx.fs.resolve()` 给出的 `displayPath` / `targetKey` 与 `read` 走的是同一套解析，
 * 模型从列目录拿到的路径可以直接喂给 `read`。`ctx.fs.listDir()` 也只 stat、不读内容
 * （官方注释：file contents are never read）。
 *
 * 为什么零依赖（硬约束）
 * --------------------
 *
 * 本插件以 `link:` 装进 profile，真实路径仍在仓库里，Node 从真实路径向上找
 * `node_modules`，走不到 `~/.dsh/profiles/node_modules`，所以 `@deepseek-ai/*`
 * 一律 import 不到（实测 ERR_MODULE_NOT_FOUND）。路径规范化只能用纯 `node:path`
 * 自己写。详见 dsh/plugins/fs-readguard/README.md。
 *
 * 工具定义是**手写的裸 ToolDefinition**：`ctx.tools.register()` 收的就是这个形状
 * （`defineTool` 只是"入参 spec → JSON Schema + 校验 + render"的便利包装）。
 * 代价是入参校验要自己做——本工具只有一个可选字符串参数，直接用 `typeof` 判。
 */

import { realpathSync } from 'node:fs';
import {
  basename,
  dirname,
  isAbsolute,
  normalize,
  relative,
  resolve as pathResolve,
  sep,
} from 'node:path';

/** 插件名。 */
export const name = 'tool-list-dir';

/** 依赖的服务：`tools` 注册表，以及提供路径解析与列目录的 `fs`。 */
export const inject = ['tools', 'fs'];

/** 模型看到的工具名。 */
const TOOL_NAME = 'list_dir';

/** 一次最多列多少项：防止超大目录把上下文塞爆。 */
const DEFAULT_MAX_ENTRIES = 200;

/**
 * 把路径规范化为绝对、且已解析符号链接的形式。
 *
 * 目标可能不存在，这时逐级向上找到最近的**已存在**祖先做 realpath，再把剩余部分拼回去。
 * 与 dsh/plugins/fs-readguard 的同名函数一致：两处都要拿"磁盘上真实的路径"做包含判断，
 * 否则 `Account/<user>/link -> /etc` 这类符号链接能绕开围栏。
 *
 * @param {string} target - 待规范化的路径（可为相对路径）。
 * @returns {string} 绝对路径。
 */
export function canonicalize(target) {
  const abs = normalize(isAbsolute(target) ? target : pathResolve(target));
  let prefix = abs;
  const rest = [];
  for (;;) {
    try {
      const real = realpathSync(prefix);
      return rest.length ? pathResolve(real, ...rest) : real;
    } catch {
      const parent = dirname(prefix);
      // 到达根仍不存在：退回词法结果。
      if (parent === prefix) return abs;
      rest.unshift(basename(prefix));
      prefix = parent;
    }
  }
}

/**
 * 去掉末尾分隔符（根除外）。
 *
 * `isInside` 的调用方给的根来自会话 header、可能带尾斜杠；这里统一掉，
 * 免得 `/a/b/` 把 `/a/b` 自己判成"不在里面"。
 *
 * @param {string} value - 路径。
 * @returns {string} 去掉尾部分隔符的路径。
 */
function stripTrailingSep(value) {
  return value.length > 1 && value.endsWith(sep) ? value.slice(0, -sep.length) : value;
}

/**
 * 判断目标是否位于某个根之内（含根本身）。
 *
 * 两侧都应是已规范化的绝对路径。比较时补分隔符是为了避免 `/a/bc` 被误判为 `/a/b` 的子路径。
 *
 * @param {string} target - 待判断的路径。
 * @param {string} root - 根。
 * @returns {boolean} 是否在根之内。
 */
export function isInside(target, root) {
  if (!target || !root) return false;
  const normalizedTarget = stripTrailingSep(target);
  const normalizedRoot = stripTrailingSep(root);
  if (normalizedTarget === normalizedRoot) return true;
  return normalizedTarget.startsWith(normalizedRoot + sep);
}

/**
 * 过滤、排序并截断目录项。
 *
 * 跳过点开头的项：它们在这个工作区里从来不是游戏内容（`.gitignore` 之类）。
 * 目录在前、文件在后，各自按名字排——与旧面板的目录树顺序一致，模型也更好扫。
 *
 * @param {{name: string, type: string}[]} entries - `ctx.fs.listDir` 的原始返回。
 * @param {number} maxEntries - 最多保留多少项。
 * @returns {{entries: {name: string, type: string}[], truncated: boolean}} 可见项与是否截断。
 */
export function visibleEntries(entries, maxEntries) {
  const visible = entries.filter((entry) => !entry.name.startsWith('.'));
  visible.sort((left, right) => {
    const leftRank = left.type === 'directory' ? 0 : 1;
    const rightRank = right.type === 'directory' ? 0 : 1;
    return leftRank !== rightRank ? leftRank - rightRank : left.name.localeCompare(right.name);
  });
  return {
    entries: visible.slice(0, maxEntries).map(({ name: entryName, type }) => ({
      name: entryName,
      type,
    })),
    truncated: visible.length > maxEntries,
  };
}

/**
 * 把结果渲染成模型读的文本。
 *
 * 一行一项，目录带尾斜杠；空目录显式说"（空）"，而不是给一片空白——
 * 模型分不清"空"和"工具没返回"。
 *
 * @param {string} dirPath - 已相对化的被列目录。
 * @param {{name: string, type: string}[]} entries - 可见项。
 * @param {boolean} truncated - 是否被截断。
 * @returns {string} 文本。
 */
export function renderListing(dirPath, entries, truncated) {
  const lines = [dirPath.endsWith('/') ? dirPath : `${dirPath}/`];
  if (entries.length === 0) {
    lines.push('（空）');
  } else {
    for (const entry of entries) {
      lines.push(`  ${entry.name}${entry.type === 'directory' ? '/' : ''}`);
    }
  }
  if (truncated) lines.push(`  …（只显示前 ${entries.length} 项）`);
  return lines.join('\n');
}

/**
 * 把绝对路径显示成相对工作目录的形式：既短，又能直接喂回 `read`。
 *
 * @param {string} cwd - 会话工作目录（列目录的上界）。
 * @param {string} target - 已解析的绝对路径。
 * @returns {string} 相对路径；工作目录本身就是 `.`。
 */
export function displayName(cwd, target) {
  const rel = relative(cwd, target);
  return rel === '' ? '.' : rel;
}

/**
 * 模型可见的工具定义。
 *
 * 入参只有一个可选字符串：`path`。根不给模型——见文件头的说明。
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - 插件上下文，提供 `fs` 服务。
 * @param {number} maxEntries - 截断上限。
 * @returns {object} 裸 ToolDefinition。
 */
export function createListDirTool(ctx, maxEntries) {
  return {
    name: TOOL_NAME,
    description:
      '列出一个目录里有哪些文件与子目录。只列一层，不递归。' +
      'path 相对本会话的工作目录（游戏流程里就是存档的 data/），例如 "world"、"status/allies"；' +
      '省略或 "." 表示工作目录本身。点开头的项不显示。' +
      '工作目录之外看不到——要读内容请拿到文件名后用 read。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        path: {
          type: 'string',
          description: '要列出的目录，相对本会话工作目录；省略或 "." 表示工作目录本身。',
        },
      },
      required: [],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string' },
          entries: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                name: { type: 'string' },
                type: { type: 'string' },
              },
              required: ['name', 'type'],
            },
          },
          truncated: { type: 'boolean' },
        },
        required: ['path', 'entries', 'truncated'],
      },
      render: (_args, value) => [
        { type: 'text', text: renderListing(value.path, value.entries, value.truncated) },
      ],
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const cwd = exec?.agent?.session?.header?.cwd;
      // 失败关闭：拿不到工作目录就无法判定上界，宁可拒绝也不放开。见 fs-readguard 的同类取舍。
      if (typeof cwd !== 'string' || cwd === '') {
        throw new Error('无法确定本会话的工作目录，已拒绝列目录。');
      }

      const requested = typeof args?.path === 'string' ? args.path.trim() : '';
      if (isAbsolute(requested)) {
        throw new Error(`path 要相对工作目录，不能是绝对路径：${requested}`);
      }

      const target = await ctx.fs.resolve(requested === '' ? '.' : requested, {
        cwd,
        signal: exec.signal,
      });

      // 双重围栏：词法判断挡住 `..` 上溯，realpath 判断挡住工作目录内的符号链接。
      // 两者都过才放行——只查一个都会漏掉另一类。
      if (!isInside(target.displayPath, cwd) || !isInside(target.targetKey, canonicalize(cwd))) {
        throw new Error(
          `只能列本会话工作目录之内的目录，${requested || '.'} 超出边界了。`,
        );
      }

      const listed = await ctx.fs.listDir(target, exec.signal);
      const { entries, truncated } = visibleEntries(listed, maxEntries);
      return {
        path: displayName(cwd, target.displayPath),
        entries,
        truncated,
      };
    },
  };
}

/**
 * 挂载工具。
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - 插件上下文（由 preset 提供）。
 * @param {{maxEntries?: number}} [config] - 插件配置。
 * @returns {void}
 */
export function apply(ctx, config) {
  const configured = config?.maxEntries;
  const maxEntries =
    typeof configured === 'number' && Number.isInteger(configured) && configured > 0
      ? configured
      : DEFAULT_MAX_ENTRIES;
  ctx.tools.register(createListDirTool(ctx, maxEntries));
}
