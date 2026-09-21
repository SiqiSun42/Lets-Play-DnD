/**
 * `dsh-tool-list-dir` 的单元测试。
 *
 * 不启动 DSH：用一个假 ctx.fs 模拟 `@deepseek-ai/dsh-fs-local` 的解析语义
 * （`displayPath` = 词法解析、`targetKey` = realpath），在一个真实的临时目录上跑。
 * 所以符号链接、`..` 上溯、点开头项这些边界是真在磁盘上验的。
 *
 * 跑：node dsh/plugins/tool-list-dir/test.mjs
 */

import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdirSync, mkdtempSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import {
  canonicalize,
  createListDirTool,
  displayName,
  isInside,
  renderListing,
  visibleEntries,
} from './index.js';

// ── 夹具 ────────────────────────────────────────────────────────────

/** 磁盘上的假工作区：`<tmp>/save/data` 是 cwd，`<tmp>/other` 在外面。 */
const root = mkdtempSync(join(tmpdir(), 'listdir-'));
const cwd = join(root, 'save', 'data');
mkdirSync(join(cwd, 'world'), { recursive: true });
mkdirSync(join(cwd, 'status'), { recursive: true });
mkdirSync(join(cwd, '.git'), { recursive: true });
writeFileSync(join(cwd, 'current_info.json'), '{}');
writeFileSync(join(cwd, 'world', '渔村杂货铺.md'), 'x');
writeFileSync(join(cwd, '.hidden'), 'x');
mkdirSync(join(root, 'other'), { recursive: true });
writeFileSync(join(root, 'other', 'secret.md'), 'x');
/** 工作区里指向外面的符号链接：只有 realpath 那道围栏能挡住它。 */
symlinkSync(join(root, 'other'), join(cwd, 'link'));

/** 测试结束清掉临时目录。 */
test.after(() => rmSync(root, { recursive: true, force: true }));

/** 与 dsh-fs-local 同语义的假 fs 服务。 */
const fakeFs = {
  async resolve(requested, { cwd: base }) {
    const displayPath = resolve(base, requested);
    let targetKey;
    try {
      targetKey = realpathSync(displayPath);
    } catch {
      targetKey = displayPath;
    }
    return { displayPath, targetKey };
  },
  async listDir(target) {
    return readdirSync(target.targetKey, { withFileTypes: true })
      .map((entry) => {
        let type = 'other';
        try {
          // 与 dsh-fs-local 一致：stat（跟随符号链接）而不是 lstat
          const info = statSync(join(target.targetKey, entry.name));
          type = info.isDirectory() ? 'directory' : info.isFile() ? 'file' : 'other';
        } catch {
          // 断链：保持 other
        }
        return { name: entry.name, type };
      })
      .sort((left, right) => left.name.localeCompare(right.name));
  },
};

/** 造一个工具执行上下文。 */
function execAt(workdir) {
  return {
    agent: workdir === undefined ? undefined : { session: { header: { cwd: workdir } } },
    signal: undefined,
  };
}

/** 插件上下文：本插件只用它的 `fs`。 */
const ctx = { fs: fakeFs };

/** 直接用裸定义跑一次工具（不走 DSH 的校验与渲染）。 */
async function runListDir(args, maxEntries, workdir = cwd) {
  const tool = createListDirTool(ctx, maxEntries ?? 200);
  return await tool.execute(args, execAt(workdir));
}

// ── 纯函数 ──────────────────────────────────────────────────────────

test('isInside：包含根本身，挡住前缀陷阱', () => {
  assert.equal(isInside('/a/b', '/a/b'), true);
  assert.equal(isInside('/a/b/c', '/a/b'), true);
  // /a/bc 不是 /a/b 的子路径——少一个分隔符就会误判
  assert.equal(isInside('/a/bc', '/a/b'), false);
  assert.equal(isInside('/a', '/a/b'), false);
  assert.equal(isInside('/a/b', '/a/b/'), true);
  assert.equal(isInside('', '/a'), false);
});

test('canonicalize：不存在的叶子挂到最近的已存在祖先上', () => {
  const missing = join(cwd, 'world', 'nope', 'deeper.md');
  // tmpdir 在 macOS 上本身是符号链接，所以这里必须用 realpath 后的 cwd 比
  assert.equal(canonicalize(missing), join(realpathSync(cwd), 'world', 'nope', 'deeper.md'));
});

test('visibleEntries：跳过点开头项、目录在前、按名排序、按上限截断', () => {
  const entries = [
    { name: 'b.md', type: 'file' },
    { name: '.hidden', type: 'file' },
    { name: 'zz', type: 'directory' },
    { name: 'a.md', type: 'file' },
    { name: 'aa', type: 'directory' },
  ];
  const all = visibleEntries(entries, 10);
  assert.deepEqual(
    all.entries.map((entry) => entry.name),
    ['aa', 'zz', 'a.md', 'b.md'],
  );
  assert.equal(all.truncated, false);

  const capped = visibleEntries(entries, 2);
  assert.deepEqual(
    capped.entries.map((entry) => entry.name),
    ['aa', 'zz'],
  );
  assert.equal(capped.truncated, true);
});

test('renderListing：目录带尾斜杠，空目录明说，截断了要讲', () => {
  assert.equal(
    renderListing('.', [{ name: 'world', type: 'directory' }, { name: 'a.md', type: 'file' }], false),
    './\n  world/\n  a.md',
  );
  assert.equal(renderListing('world', [], false), 'world/\n（空）');
  assert.equal(renderListing('.', [{ name: 'a.md', type: 'file' }], true), './\n  a.md\n  …（只显示前 1 项）');
});

test('displayName：工作目录本身显示成 .', () => {
  assert.equal(displayName(cwd, cwd), '.');
  assert.equal(displayName(cwd, join(cwd, 'world')), 'world');
});

// ── 工具本体 ────────────────────────────────────────────────────────

test('列工作目录本身：给相对化的路径，目录在前，点开头项不可见', async () => {
  const value = await runListDir({});
  assert.equal(value.path, '.');
  assert.equal(value.truncated, false);
  assert.deepEqual(
    value.entries.map((entry) => entry.name),
    ['link', 'status', 'world', 'current_info.json'],
  );
  // 点开头的项与目录里的内容都不出现
  assert.equal(value.entries.some((entry) => entry.name === '.hidden'), false);
  assert.equal(value.entries.some((entry) => entry.name === '.git'), false);
});

test('列子目录：路径可直接喂回 read', async () => {
  const value = await runListDir({ path: 'world' });
  assert.equal(value.path, 'world');
  assert.deepEqual(value.entries, [{ name: '渔村杂货铺.md', type: 'file' }]);
});

test('省略 path 与 "." 等价', async () => {
  const omitted = await runListDir({});
  const dotted = await runListDir({ path: '.' });
  assert.deepEqual(omitted, dotted);
});

test('拒绝绝对路径', async () => {
  await assert.rejects(() => runListDir({ path: join(root, 'other') }), /不能是绝对路径/);
});

test('拒绝用 .. 上溯出工作目录', async () => {
  await assert.rejects(() => runListDir({ path: '../..' }), /超出边界了/);
  await assert.rejects(() => runListDir({ path: 'world/../../..' }), /超出边界了/);
  // 上溯到存档根那一层也不行：上界就是工作目录自己
  await assert.rejects(() => runListDir({ path: '..' }), /超出边界了/);
});

test('拒绝穿过符号链接走到工作目录之外', async () => {
  // 词法上看 "link" 就在 cwd 里面，只有 realpath 那道围栏能挡住
  await assert.rejects(() => runListDir({ path: 'link' }), /超出边界了/);
  await assert.rejects(() => runListDir({ path: 'link/secret.md' }), /超出边界了/);
});

test('link/.. 词法上塌回工作目录，没有越界（真去遍历磁盘才会到外面）', async () => {
  const value = await runListDir({ path: 'link/..' });
  assert.equal(value.path, '.');
});

test('拿不到会话工作目录时失败关闭', async () => {
  // 注意用 null 而不是 undefined：undefined 会命中 `workdir = cwd` 这个默认参数，
  // 测不到想测的分支（这坑踩过一次）
  await assert.rejects(() => runListDir({}, 200, null), /无法确定本会话的工作目录/);
  await assert.rejects(() => runListDir({}, 200, ''), /无法确定本会话的工作目录/);
});

test('按上限截断', async () => {
  const value = await runListDir({}, 2);
  assert.equal(value.entries.length, 2);
  assert.equal(value.truncated, true);
});

test('返回的 value 只带 schema 声明的字段', async () => {
  const value = await runListDir({ path: 'world' });
  assert.deepEqual(Object.keys(value).sort(), ['entries', 'path', 'truncated']);
  assert.deepEqual(Object.keys(value.entries[0]).sort(), ['name', 'type']);
});
