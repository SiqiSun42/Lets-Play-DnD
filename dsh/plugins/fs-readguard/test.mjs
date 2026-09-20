/**
 * fs-readguard 的单元测试：不启动 DSH，直接喂假的 exec 对象。
 *
 * 运行：node dsh/plugins/fs-readguard/test.mjs
 *
 * 为什么单独测：这个守卫是安全控制，它的失败模式必须是"吵闹"的。
 * 覆盖的重点不是"正常情况能读"，而是**它能不能拒绝**——尤其是
 * 路径穿越、符号链接、前缀陷阱这三类看起来像在里面、实际在外面的写法。
 */

import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { createReadGuard, name } from './index.js';

let pass = 0;
let fail = 0;

function check(condition, label) {
  if (condition) {
    pass += 1;
    console.log(`  PASS  ${label}`);
  } else {
    fail += 1;
    console.log(`  FAIL  ${label}`);
  }
}

/** 构造一次工具调用的执行上下文。 */
function exec(toolName, args, cwd) {
  return {
    name: toolName,
    arguments: args,
    agent: cwd === undefined ? undefined : { session: { header: { cwd } } },
  };
}

const root = mkdtempSync(join(tmpdir(), 'readguard-'));
const save = join(root, 'Account', 'alice');
const skills = join(root, 'Skills');
const outside = join(root, 'outside');
const sibling = join(root, 'Account', 'alice-other');

mkdirSync(save, { recursive: true });
mkdirSync(skills, { recursive: true });
mkdirSync(outside, { recursive: true });
mkdirSync(sibling, { recursive: true });
writeFileSync(join(save, 'inventory.md'), '长剑 x1\n');
writeFileSync(join(skills, 'SKILL.md'), '# consult\n');
writeFileSync(join(root, '.env'), 'FLASK_SECRET_KEY=x\n');
writeFileSync(join(root, 'account.db'), 'binary\n');
writeFileSync(join(sibling, 'leak.md'), '别人的存档\n');
writeFileSync(join(outside, 'secret.md'), '机密\n');
// 预先存在的符号链接：指向工作区之外。模型自己无法制造符号链接（没有 shell），
// 但目录里本来就可能有一个，围栏必须穿透它。
symlinkSync(outside, join(save, 'link-out'));

const guard = createReadGuard({ readRoots: [skills] });

console.log('=== 允许：会话工作区内 ===');
check(guard(exec('read', { file_path: join(save, 'inventory.md') }, save)) === undefined,
  '绝对路径：读工作区内的文件');
check(guard(exec('read', { file_path: 'inventory.md' }, save)) === undefined,
  '相对路径：按会话 cwd 解析');
check(guard(exec('read', { file_path: save }, save)) === undefined,
  '根本身');
check(guard(exec('read', { file_path: join(save, 'sub', 'new.md') }, save)) === undefined,
  '不存在的文件也按词法判定（工具自己去报"找不到"）');

console.log('\n=== 允许：显式配置的技能根 ===');
check(guard(exec('read', { file_path: join(skills, 'SKILL.md') }, save)) === undefined,
  '读 Skills/ 下的技能说明');

console.log('\n=== 拒绝：工作区之外的秘密 ===');
for (const [label, path] of [
  ['.env', join(root, '.env')],
  ['account.db', join(root, 'account.db')],
  ['~/.dsh/.credentials.yaml', '/Users/nobody/.dsh/.credentials.yaml'],
  ['/proc/self/environ', '/proc/self/environ'],
  ['/etc/passwd', '/etc/passwd'],
]) {
  const reason = guard(exec('read', { file_path: path }, save));
  check(typeof reason === 'string' && reason.includes('readguard'), `拒绝读 ${label}`);
}

console.log('\n=== 拒绝：路径穿越与别名 ===');
check(typeof guard(exec('read', { file_path: '../../.env' }, save)) === 'string',
  '相对路径向上穿越到项目根');
check(typeof guard(exec('read', { file_path: join(save, '..', '..', '.env') }, save)) === 'string',
  '绝对路径里夹 ..');
check(typeof guard(exec('read', { file_path: join(save, 'link-out', 'secret.md') }, save)) === 'string',
  '穿过已有的符号链接指向工作区外');
check(typeof guard(exec('read', { file_path: join(sibling, 'leak.md') }, save)) === 'string',
  '前缀陷阱：alice 不能读 alice-other');
check(typeof guard(exec('read', { file_path: join(root, 'Account') }, save)) === 'string',
  '父目录不是工作区');

console.log('\n=== read_image 同样受管 ===');
check(guard(exec('read_image', { file_path: join(save, 'map.png') }, save)) === undefined,
  'read_image 读工作区内');
check(typeof guard(exec('read_image', { file_path: join(root, '.env') }, save)) === 'string',
  'read_image 读 .env 被拒');

console.log('\n=== 不受本守卫管辖的调用 ===');
check(guard(exec('write', { file_path: join(root, 'x.md') }, save)) === undefined,
  'write 放行（交由 sandbox-policy 处理）');
check(guard(exec('edit', { file_path: join(root, 'x.md') }, save)) === undefined,
  'edit 放行（交由 sandbox-policy 处理）');
check(guard(exec('skill', { name: 'consult' }, save)) === undefined,
  'skill 放行（技能加载器自己读 SKILL.md）');
check(guard(exec('mcp__letsplaydnd__search_rules', { query: '火球术' }, save)) === undefined,
  'MCP 工具放行（不碰文件系统）');
check(guard(exec('read', {}, save)) === undefined,
  '缺少 file_path：交给工具自己的入参校验');
check(guard(exec('read', { file_path: '' }, save)) === undefined,
  '空 file_path：交给工具自己的入参校验');

console.log('\n=== 失败关闭 ===');
check(typeof guard(exec('read', { file_path: join(save, 'inventory.md') }, undefined)) === 'string',
  '拿不到会话 cwd 时拒绝（而不是放行）');

console.log('\n=== 插件元信息 ===');
check(name === 'fs-readguard', '导出插件名');
check(typeof createReadGuard === 'function', '导出守卫工厂');

rmSync(root, { recursive: true, force: true });

console.log(`\n${pass} PASS / ${fail} FAIL`);
process.exit(fail ? 1 : 0);
