// python.js — dsh-bio-graft Python 子进程调用器（JSON stdin 协议）
// bridge 契约同 dsh-bio-genie/gem：stdout 最后一行是 JSON；stderr 含
// "Traceback (most recent call last)" 头 = 代码级失败（恒 ok:true 时靠它判定）。
import { spawn, spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import os from 'node:os'

const PYTHON_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'python')

/**
 * 候选解释器，按优先级（通用化，不写死本机路径）：
 *   1. `GRAFT_PYTHON`  — 用户显式指定，最高优先级
 *   2. 宿主自举环境     — `$DSH_HOME/dsh-bio-genie/python-env`（genie 第一层
 *      依赖含 matplotlib/pandas/mpi4py/biopython 等，graft 无需额外科学生物库
 *      —— v0.1 核心是纯对象/正则，不需要 cobra/gapseq 级重量依赖）
 *   3. `CONDA_PREFIX`  — 当前激活的 conda 环境
 *   4. `python`        — PATH 兜底
 *
 * 探测：graft v0.1 要求 json/re（stdlib），任何 Python3 即可；但我们要保证
 * 解释器至少能跑 guides/offtarget（import 不炸）。
 */
export function pythonCandidates() {
  const list = []
  if (process.env.GRAFT_PYTHON) list.push({ path: process.env.GRAFT_PYTHON, source: 'GRAFT_PYTHON' })
  const dshHome = process.env.DSH_HOME ?? join(os.homedir(), '.dsh')
  const hosted = join(dshHome, 'dsh-bio-genie', 'python-env')
  list.push({
    path: process.platform === 'win32'
      ? join(hosted, 'Scripts', 'python.exe')
      : join(hosted, 'bin', 'python'),
    source: 'genie-hosted',
  })
  if (process.env.CONDA_PREFIX) {
    list.push({
      path: process.platform === 'win32'
        ? join(process.env.CONDA_PREFIX, 'python.exe')
        : join(process.env.CONDA_PREFIX, 'bin', 'python'),
      source: 'CONDA_PREFIX',
    })
  }
  list.push({ path: 'python', source: 'PATH' })
  return list
}

// graft v0.1 的核心 op 纯标准库；但为了 unifying 用户体验仍走 genie-hosted 优先
function hasBaseline(exe) {
  try {
    const r = spawnSync(exe, ['-I', '-c', 'import json, re'], {
      timeout: 2_000, windowsHide: true, stdio: 'ignore',
    })
    return r.status === 0
  } catch {
    return false
  }
}

let cachedSelection = null
let cachedSelectionAt = 0
const SELECTION_CACHE_MS = 60_000

/** 状态端点与实际执行共享同一次验证，避免仅因文件存在而误报可用。 */
export function pythonSelection() {
  if (cachedSelection && Date.now() - cachedSelectionAt < SELECTION_CACHE_MS) return cachedSelection
  const candidates = pythonCandidates().map((candidate) => ({
    ...candidate,
    exists: candidate.path === 'python' ? null : existsSync(candidate.path),
    validated: false,
  }))
  let selected = null
  for (const candidate of candidates) {
    if (candidate.exists === false) continue
    candidate.validated = hasBaseline(candidate.path)
    if (candidate.validated) {
      selected = candidate
      break
    }
  }
  cachedSelection = { selected, candidates }
  cachedSelectionAt = Date.now()
  return cachedSelection
}

export function pythonExe() {
  const selected = pythonSelection().selected
  if (!selected) throw new Error('no usable Python interpreter (set GRAFT_PYTHON or install Genie Python environment)')
  return selected.path
}

/** graft v0.1 的 op 全部与工具同名（graft_<op>）。 */
function toolNameFor(op) {
  return `graft_${op}`
}

/**
 * 与 dsh-bio-genie/gem 溯源契约对齐：工具输出挂 `_provenance`。
 */
export function stampProvenance(tool, value) {
  if (value && typeof value === 'object' && !Array.isArray(value) && value._provenance === undefined) {
    value._provenance = { tool, at: new Date().toISOString() }
  }
  return value
}

/** 调用 graft_ops.py（op 协议）：{op, args} -> result；异常/代码级失败抛 Error。 */
export function callGraft(op, args, opts = {}) {
  return new Promise((resolve, reject) => {
    let py
    try { py = pythonExe() } catch (error) { reject(error); return }
    const script = join(PYTHON_DIR, 'graft_ops.py')
    const cp = spawn(py, ['-I', script], { cwd: opts.cwd || PYTHON_DIR, windowsHide: true })
    let out = ''
    let err = ''
    cp.stdout.on('data', (d) => { out += d })
    cp.stderr.on('data', (d) => { err += d })
    cp.on('error', (e) => reject(new Error(`python spawn failed (${py}): ${e.message}`)))
    const timer = opts.timeoutMs
      ? setTimeout(() => { cp.kill(); reject(new Error(`graft op ${op} timeout after ${opts.timeoutMs}ms`)) }, opts.timeoutMs)
      : null
    cp.on('close', (code) => {
      if (timer) clearTimeout(timer)
      const lines = out.trim().split(/\r?\n/).filter(Boolean)
      if (!lines.length) {
        return reject(new Error(`graft_ops.py produced no output (op=${op}, python=${py}); stderr: ${err.slice(-400)}`))
      }
      if (err.includes('Traceback (most recent call last)')) {
        return reject(new Error(`graft op ${op} code-level failure: ${err.slice(-400)}`))
      }
      let parsed
      try {
        parsed = JSON.parse(lines[lines.length - 1])
      } catch (e) {
        return reject(new Error(`graft op ${op} bad JSON: ${lines[lines.length - 1].slice(0, 300)}`))
      }
      if (parsed.ok === false) return reject(new Error(parsed.error || `graft op ${op} failed (ok:false)`))
      resolve(stampProvenance(toolNameFor(op), parsed.result))
    })
    cp.stdin.write(JSON.stringify({ op, args }))
    cp.stdin.end()
  })
}

export { PYTHON_DIR }
