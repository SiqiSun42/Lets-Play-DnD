/**
 * LetsPlayDnD 的模型文件读取白名单（spec.md P5-1）。
 *
 * 为什么是白名单而不是黑名单
 * --------------------------
 *
 * 两者实现成本完全相同——同一个检查点、同一段代码，只是比较方向反过来。
 * 差别只在失败模式：
 *
 * - 黑名单：出现一个未列入的新秘密文件 → **静默 + 灾难**；且要求穷举"现在和未来所有秘密"。
 * - 白名单：模型读不到某个正当文件 → **吵闹 + 无害**（模型会报告读不到，加一个根即可）。
 *
 * 白名单只需枚举**我们自己的**目录，不需要枚举秘密。所以用白名单。
 *
 * 为什么用 ctx.tools.guard 而不是 tools/pre-execute
 * ------------------------------------------------
 *
 * guard 是**单调**的：它跑在可扩展的 pre-execute waterfall 之后，只能拒绝、不能放行，
 * 因此监听器顺序无法把一个拒绝翻回允许。用在安全控制上这是正确语义。
 *
 * 为什么只拦 read / read_image
 * ---------------------------
 *
 * 写围栏已经由 host 平面的 `sandbox-policy`（workspace-write，可写根 = 会话 cwd）负责，
 * 它还会给出升权提示。这里再拦一次写，只会让同一件事出现两套冲突的报错。
 * 本插件只补那条缺失的规则：**读**。
 *
 * 为什么是"策略"而不是"内核边界"
 * ----------------------------
 *
 * 这是可信代码中对模型可控路径的检查，不是内核边界——它的完备性依赖一个前提：
 * **本预设内没有可执行代码**（无 bash / pwsh / 带 shell 的 subagent）。
 * 没有 shell，`read` 就是唯一的读路径，路径级围栏才成立。
 * 这个前提是硬性的：一旦引入 shell，本插件静默失效。
 * 依据见 spec.md P5-1「不变量」与 §8 约束 1。
 *
 * 为什么不 import 任何 @deepseek-ai/* 包
 * ------------------------------------
 *
 * 本插件被安装进 profile 的 node_modules（见 dsh/plugins/fs-readguard/README.md），
 * 那里解析不到 dsh 安装目录下的包。所以路径规范化用纯 node:fs 自己实现，零依赖。
 */

import { realpathSync } from 'node:fs';
import {
  basename,
  dirname,
  isAbsolute,
  normalize,
  resolve as pathResolve,
  sep,
} from 'node:path';

/** 插件名。 */
export const name = 'fs-readguard';

/** 依赖的服务：没有 tools 注册表就无处挂守卫。 */
export const inject = ['tools'];

/**
 * 受管的读工具 → 其路径参数的字段名。
 *
 * 字段名是 snake_case，与 tool-fs 的模型接口一致。
 * `write` / `edit` 刻意不在这里：写由 sandbox-policy 负责。
 */
const READ_TOOLS = new Map([
  ['read', 'file_path'],
  ['read_image', 'file_path'],
]);

/** 被拒时返回给模型的稳定标记，便于测试与日志检索。 */
const DENY_MARKER = '[readguard: read denied]';

/**
 * 把路径规范化为绝对、且已解析符号链接的形式。
 *
 * 目标可能不存在（例如读一个不存在的文件）。这时逐级向上找到最近的**已存在**祖先，
 * 对它做 realpath，再把剩余部分拼回去。这样：
 *
 * - 不存在的目标也能得到稳定、可比较的路径；
 * - 经由符号链接到达的路径会被解析成真实位置，`Account/<user>/link -> /opt/...`
 *   这类已有的链接无法绕开围栏。
 *
 * 模型自身无法制造符号链接（没有 shell，`write` 只写文本内容），所以这里不处理
 * "检查后、open 前"的竞态——那需要在 seam 内部做，属另一个威胁模型。
 *
 * @param {string} target - 待规范化的路径（可为相对路径）。
 * @returns {string} 绝对路径。
 */
function canonicalize(target) {
  const abs = normalize(isAbsolute(target) ? target : pathResolve(target));
  let prefix = abs;
  const rest = [];
  for (;;) {
    try {
      const real = realpathSync(prefix);
      return rest.length ? pathResolve(real, ...rest) : real;
    } catch {
      const parent = dirname(prefix);
      // 到达根仍不存在（例如 Windows 上的不存在盘符）：退回词法结果。
      if (parent === prefix) return abs;
      rest.unshift(basename(prefix));
      prefix = parent;
    }
  }
}

/**
 * 判断目标是否位于某个根之内（含根本身）。
 *
 * 两侧都已 realpath，所以磁盘上真实拼写一致的路径必然逐字相等。
 * 这里按大小写敏感比较：大小写不敏感卷上的差异由 realpath 归一，而真正不存在的
 * 目标本来也读不到。加尾部分隔符是为了避免 `/a/bc` 被误判为 `/a/b` 的子路径。
 *
 * @param {string} target - 已规范化的目标。
 * @param {string} root - 未规范化的根（函数内部规范化）。
 * @returns {boolean} 是否在根之内。
 */
function isInside(target, root) {
  if (!root) return false;
  const canonicalRoot = canonicalize(root);
  if (target === canonicalRoot) return true;
  const withSep = canonicalRoot.endsWith(sep) ? canonicalRoot : canonicalRoot + sep;
  return target.startsWith(withSep);
}

/**
 * 取出本次调用声明的路径参数，且只接受非空字符串。
 *
 * 参数缺失或类型不对时返回 undefined——那是工具自身的入参校验问题，
 * 交给它报错，守卫不越权解释。
 *
 * @param {object} exec - 工具执行上下文。
 * @param {string} argName - 参数名。
 * @returns {string|undefined} 路径，或 undefined。
 */
function requestedPath(exec, argName) {
  const args = exec?.arguments;
  if (!args || typeof args !== 'object') return undefined;
  const value = args[argName];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

/**
 * 本次调用所属会话的工作区（存档）目录。
 *
 * 与 `dsh-tool-fs` 取 cwd 的方式一致：`agent.session.header.cwd`。
 * 不能退回 `process.cwd()`——那是 DSH 进程的启动目录，不是会话工作区，
 * 用它当根会让围栏圈错地方。
 *
 * @param {object} exec - 工具执行上下文。
 * @returns {string|undefined} 会话 cwd。
 */
function sessionCwd(exec) {
  return exec?.agent?.session?.header?.cwd;
}

/**
 * 构造守卫函数。导出以便脱离 DSH 单独做单元测试。
 *
 * @param {{readRoots?: (string|undefined|null)[]}} [config] - 插件配置。
 * @returns {(exec: object) => (string|undefined)} 同步守卫：返回原因即拒绝，返回 undefined 即放行。
 */
export function createReadGuard(config = {}) {
  const readRoots = (config?.readRoots ?? []).filter(
    (root) => typeof root === 'string' && root.length > 0,
  );

  return function guard(exec) {
    const argName = READ_TOOLS.get(exec?.name);
    if (argName === undefined) return undefined;

    const requested = requestedPath(exec, argName);
    if (requested === undefined) return undefined;

    const cwd = sessionCwd(exec);
    // 失败关闭：拿不到会话工作区就无法判定允许范围，宁可拒绝也不放行。
    // 放行是静默失败，拒绝是吵闹失败——后者才是这个控制该有的失败方向。
    if (cwd === undefined || cwd === '') {
      return `${DENY_MARKER} 无法确定会话工作区（缺少 agent.session.header.cwd），已拒绝。`;
    }

    const target = canonicalize(isAbsolute(requested) ? requested : pathResolve(cwd, requested));
    for (const root of [cwd, ...readRoots]) {
      if (isInside(target, root)) return undefined;
    }

    return (
      `${DENY_MARKER} ${requested} 不在允许读取的范围内，已拒绝。` +
      `本会话只允许读取它自己的工作区，以及技能说明文件。`
    );
  };
}

/**
 * 挂载守卫。
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - 插件上下文（由 preset 提供）。
 * @param {{readRoots?: string[]}} [config] - 插件配置。
 * @returns {void}
 */
export function apply(ctx, config) {
  ctx.tools.guard(createReadGuard(config));
}
