// test/tools-contract.mjs — 工具注册契约（不依赖 dsh 引擎，用 mock loader 替换 @deepseek-ai/dsh-tools）
//
// 断言：
//   ① 注册的工具集合正好是文档化的 7 个；
//   ② 所有 object 型参数都显式声明 additionalProperties（缺失会让 dsh 启动 UNSUPPORTED_SCHEMA）；
//   ③ src/tools.js 里引用的每个 op（op: 'x' / callGraft('x')）都能在 python/graft_ops.py 的
//      OPS 里找到 —— 防「注册了工具但 Python 未实现」这类只在真实会话里才暴露的静默失败。
import './register-dsh-tools.mjs'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { check, summary, REPO } from './harness.mjs'

const toolsMod = await import('../src/tools.js')

const registered = []
const ctx = {
  tools: { register: (def) => { registered.push(def); return () => {} } },
  effect: () => () => {},
}
toolsMod.registerTools(ctx)

const EXPECTED = [
  'graft_backend_status',
  'graft_base_edit',
  'graft_design',
  'graft_offtarget',
  'graft_plan_load',
  'graft_plan_save',
  'graft_profiles',
  'graft_rank',
  'graft_score',
  'graft_strategy',
]

check('registers exactly the documented tool set',
  registered.map((t) => t.name).sort().join(',') === EXPECTED.join(','),
  `got: ${registered.map((t) => t.name).join(',')}`)

for (const tool of registered) {
  for (const [key, spec] of Object.entries(tool.parameters ?? {})) {
    const target = spec?.items?.type === 'object' ? spec.items : spec
    if (target?.type === 'object') {
      check(`${tool.name}.${key} declares additionalProperties`,
        target.additionalProperties === true || target.additionalProperties === false,
        '(dsh schema validator raises UNSUPPORTED_SCHEMA without it)')
    }
  }
}

const opsSource = readFileSync(join(REPO, 'python', 'graft_ops.py'), 'utf8')
const opsStart = opsSource.indexOf('OPS = {')
const opsEnd = opsSource.indexOf('def main()')
const opsBlock = opsSource.slice(opsStart, opsEnd)

const toolsSource = readFileSync(join(REPO, 'src', 'tools.js'), 'utf8')
const referenced = new Set()
for (const m of toolsSource.matchAll(/op:\s*'([a-z_]+)'/g)) referenced.add(m[1])
for (const m of toolsSource.matchAll(/callGraft\('([a-z_]+)'/g)) referenced.add(m[1])

check('src/tools.js references at least one op per tool',
  referenced.size >= registered.length,
  `referenced=${[...referenced].join(',')}`)

for (const opName of [...referenced].sort()) {
  check(`op "${opName}" exists in graft_ops OPS`, opsBlock.includes(`'${opName}'`))
}

// ---------- 分支型工具必须真的走到自己的 execute ----------
// 回归背景（2026-09-14 真实会话）：工具工厂无条件覆盖 execute，导致 graft_backend_status
// 的 status/devices/ensure 三个分支永远失效，落到 callGraft(undefined) → "unknown op: None"。
const backendTool = registered.find((t) => t.name === 'graft_backend_status')
check('graft_backend_status is registered', Boolean(backendTool))
if (backendTool) {
  const st = await backendTool.execute({ action: 'status' })
  check('graft_backend_status(action=status) reaches the offtarget_backend op',
    Boolean(st && typeof st.backend === 'object' && 'ok' in st.backend),
    JSON.stringify(st).slice(0, 200))
  const dev = await backendTool.execute({ action: 'devices' })
  check('graft_backend_status(action=devices) returns the OpenCL device list',
    Array.isArray(dev?.devices), JSON.stringify(dev).slice(0, 200))
}

summary('tools-contract')
