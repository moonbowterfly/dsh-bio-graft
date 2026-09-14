// test/harness.mjs — graft 测试公共工具（零第三方依赖）
//
// 纪律（家族教训）：
//   ① 不用 process.exit()（管道下会截断未刷新的 stdout），改用 process.exitCode；
//   ② 探针失败/跳过在 GRAFT_STRICT=1 下必须变成 FAIL（"门不许静默跳过"）；
//   ③ 直驱 graft_ops.py 的 stdin 协议（脚本走 argv，stdin 留给 payload）。
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import os from 'node:os'

export const REPO = join(dirname(fileURLToPath(import.meta.url)), '..')
export const PYDIR = join(REPO, 'python')
export const STRICT = process.env.GRAFT_STRICT === '1'

let passed = 0
let failed = 0
const failures = []

export function check(name, cond, detail = '') {
  if (cond) {
    passed += 1
    console.log(`  ok   ${name}`)
  } else {
    failed += 1
    failures.push(name)
    console.log(`  FAIL ${name} ${detail}`)
  }
}

export function skip(name, reason) {
  if (STRICT) {
    check(name, false, `(skipped: ${reason}; GRAFT_STRICT=1 forbids silent skips)`)
    return false
  }
  console.log(`  skip ${name} (${reason})`)
  return true
}

export function summary(label) {
  console.log(`\n${label}: ${passed} passed, ${failed} failed`)
  if (failed) {
    console.log('failed cases:\n  - ' + failures.join('\n  - '))
    process.exitCode = 1
  }
  return failed === 0
}

function pythonCandidates() {
  const list = []
  if (process.env.GRAFT_PYTHON) list.push(process.env.GRAFT_PYTHON)
  const dshHome = process.env.DSH_HOME ?? join(os.homedir(), '.dsh')
  list.push(process.platform === 'win32'
    ? join(dshHome, 'dsh-bio-genie', 'python-env', 'Scripts', 'python.exe')
    : join(dshHome, 'dsh-bio-genie', 'python-env', 'bin', 'python'))
  if (process.env.CONDA_PREFIX) {
    list.push(process.platform === 'win32'
      ? join(process.env.CONDA_PREFIX, 'python.exe')
      : join(process.env.CONDA_PREFIX, 'bin', 'python'))
  }
  list.push('python')
  return list
}

export function pythonExe() {
  for (const exe of pythonCandidates()) {
    if (!exe) continue
    if (exe !== 'python' && !existsSync(exe)) continue
    const probe = spawnSync(exe, ['-I', '-c', 'import json, re'], { windowsHide: true })
    if (probe.status === 0) return exe
  }
  throw new Error('no usable python interpreter (set GRAFT_PYTHON to override)')
}

/** 直驱 graft_ops.py：{op, args} -> result；代码级失败（traceback / ok:false）抛错。 */
export function op(opName, args = {}, { timeoutMs = 120_000 } = {}) {
  const py = pythonExe()
  const res = spawnSync(py, ['-I', join(PYDIR, 'graft_ops.py')], {
    cwd: PYDIR,
    input: JSON.stringify({ op: opName, args }),
    encoding: 'utf8',
    timeout: timeoutMs,
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  })
  const err = res.stderr || ''
  if (err.includes('Traceback (most recent call last)')) {
    throw new Error(`op ${opName} traceback: ${err.slice(-600)}`)
  }
  const line = (res.stdout || '').trim().split(/\r?\n/).filter(Boolean).pop()
  if (!line) throw new Error(`op ${opName} produced no output; stderr=${err.slice(-300)}`)
  let parsed
  try {
    parsed = JSON.parse(line)
  } catch (e) {
    throw new Error(`op ${opName} returned non-JSON: ${line.slice(0, 200)}`)
  }
  if (parsed.ok !== true) throw new Error(`op ${opName} ok:false -> ${parsed.error}`)
  return parsed.result
}
