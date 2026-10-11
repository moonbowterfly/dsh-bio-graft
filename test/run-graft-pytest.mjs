// run-graft-pytest.mjs — 用 graft 运行时候选解释器跑一个 Python 测试文件（纯标准库），
// 退出码透传（测试失败 → 非零退出，形成闸门）。
// 用法：node test/run-graft-pytest.mjs test/test_gf_contract.py
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync } from 'node:fs'
import { pythonCandidates } from '../src/python.js'

const testFile = process.argv[2]
if (!testFile) {
  console.error('usage: node test/run-graft-pytest.mjs <test.py>')
  process.exit(2)
}
const repo = join(dirname(fileURLToPath(import.meta.url)), '..')
const abs = join(repo, testFile)

function probe(exe) {
  try {
    const r = spawnSync(exe, ['-I', '-c', 'import json, re'], { timeout: 30_000, windowsHide: true, stdio: 'ignore' })
    return r.status === 0
  } catch {
    return false
  }
}

let exe = null
for (const c of pythonCandidates()) {
  if (!c.path) continue
  if (c.path !== 'python' && !existsSync(c.path)) continue
  if (probe(c.path)) { exe = c.path; break }
}
if (!exe) {
  console.error('[run-graft-pytest] 找不到可 import json/re 的解释器')
  process.exit(2)
}

// stdio:inherit 规避本环境 pipe 捕获 python.exe 时的 EBUSY（见 REPORT 环境限制）
const r = spawnSync(exe, ['-I', '-B', abs], {
  cwd: repo, stdio: 'inherit',
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
})
if (r.status !== 0) {
  console.error(`\n[run-graft-pytest] ${testFile} FAILED (interpreter=${exe}, exit=${r.status})`)
  process.exit(r.status ?? 1)
}
console.log(`\n[run-graft-pytest] ${testFile} PASS (interpreter=${exe})`)
