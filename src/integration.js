/**
 * dsh-bio-graft — hosted-domain integration protocol v1 (read-only batch).
 *
 * 协议形状与 dsh-bio-gem（gem-hosted extension）v1 相同，宿主（genie）的
 * classifyGemState() 五态判定消费它：
 *   GET {prefix}/health   — 静态字段（不 spawn Python，不写盘）
 *   GET {prefix}/v1/status — 运行时状态（interpreter / backend / plans / 摘要）
 *
 * This module deliberately has no import-time probes: loading the plugin and
 * serving /health must never spawn Python or modify the data directory.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import os from 'node:os'
import { join } from 'node:path'
import { pythonCandidates } from './python.js'

export const INTEGRATION_PREFIX = '/api/dsh-bio-graft/integration'
export const PROTOCOL_MAJOR = 1
export const PROTOCOL_MINORS = [0]
export const RUNTIME_PROBE_CACHE_MS = 60_000
export const INTEGRATION_FEATURES = [
  'status',
  'editor-registry',
  'editplans',
  'cas-offinder',
]

const PLUGIN_ID = 'dsh-bio-graft'
const PLUGIN_VERSION = '0.1.0'

function defaultDataRoot() {
  const dshHome = process.env.DSH_HOME ?? join(os.homedir(), '.dsh')
  return join(dshHome, 'dsh-bio-graft')
}

function listFiles(dir, predicate = () => true) {
  try {
    if (!existsSync(dir)) return []
    return readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isFile() && predicate(e.name))
      .map((e) => ({
        name: e.name,
        size: statSync(join(dir, e.name)).size,
        mtime: statSync(join(dir, e.name)).mtime.toISOString(),
      }))
  } catch {
    return []
  }
}

function loopbackOnly(req) {
  const sa = req.socket?.remoteAddress ?? ''
  const loopbackIp = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(sa)
  if (!loopbackIp) return false
  try {
    const host = (req.headers?.host ?? '').split(':')[0]
    const okHost = ['127.0.0.1', 'localhost', '[::1]'].includes(host)
    if (!okHost) return false
    const site = req.headers?.['sec-fetch-site']
    if (site && site === 'cross-site') return false
    const origin = req.headers?.origin
    if (origin) {
      const oh = new URL(origin).hostname
      if (oh !== host) return false
    }
    return true
  } catch {
    return false
  }
}

function writeJson(res, status, body) {
  const text = JSON.stringify(body, null, 2)
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(text)
}

/** 静态/半静态 health 载荷。 */
function healthPayload() {
  const dshHome = process.env.DSH_HOME ?? join(os.homedir(), '.dsh')
  return {
    plugin: PLUGIN_ID,
    pluginVersion: PLUGIN_VERSION,
    protocol: { major: PROTOCOL_MAJOR, minors: PROTOCOL_MINORS },
    features: INTEGRATION_FEATURES,
    dataRoot: defaultDataRoot(),
    checks: {
      pythonCandidates: pythonCandidates().map((c) => ({ path: c.path, source: c.source })),
      casOffinderBin: existsSync(join(dshHome, 'dsh-bio-graft', 'bin', 'cas-offinder.exe')),
      plansDir: existsSync(join(dshHome, 'dsh-bio-graft', 'plans')),
    },
  }
}

/**
 * 运行时 status（昂贵探测，60s 缓存）。
 * 返回 state ∈ {ready, degraded} + pending 缺项摘要。
 */
export function createIntegrationService() {
  let cachedStatus = null
  let cachedAt = 0

  async function status() {
    if (cachedStatus && (Date.now() - cachedAt) < RUNTIME_PROBE_CACHE_MS) return cachedStatus
    const dataRoot = defaultDataRoot()
    const plansDir = join(dataRoot, 'plans')
    const binDir = join(dataRoot, 'bin')
    const casExe = join(binDir, 'cas-offinder.exe')

    const checks = {}
    checks.plansDir = { status: existsSync(plansDir) ? 'ok' : 'missing' }
    checks.casOffinder = { status: existsSync(casExe) ? 'ok' : 'missing',
                           install_hint: existsSync(casExe) ? undefined
                             : 'graft_backend_status action=ensure 自动安装 BSD-3 二进制' }
    // python 解释器探测（不 spawn，读 pythonCandidates；真正 import 探测由 graft op 做）
    const py = pythonCandidates()
    checks.interpreter = {
      status: py.length ? 'ok' : 'missing',
      selected: py[0]?.path ?? null,
      candidates: py.map((c) => ({ path: c.path, source: c.source })),
    }

    const plans = listFiles(plansDir, (n) => n.endsWith('.editplan.json'))
    const nonOk = Object.entries(checks).filter(([, v]) => v?.status !== 'ok')
    const state = nonOk.length === 0 ? 'ready' : 'degraded'
    const value = {
      plugin: PLUGIN_ID,
      pluginVersion: PLUGIN_VERSION,
      state,
      checks,
      data: {
        plans: { count: plans.length, entries: plans.slice(0, 50) },
        casOffinder: { present: existsSync(casExe) },
      },
      env: {
        interpreter: py.length ? { selected: py[0].path, source: py[0].source } : null,
      },
      remediations: nonOk.length > 0
        ? nonOk.map(([k]) => ({ code: `graft.remediate-${k}`, owner: 'graft' }))
        : [],
      protocol: { major: PROTOCOL_MAJOR, minors: PROTOCOL_MINORS },
    }
    cachedStatus = value
    cachedAt = Date.now()
    return value
  }

  return { status, invalidate: () => { cachedStatus = null; cachedAt = 0 } }
}

/** 注册 integration 路由（loopback-only 守卫 + 20s 硬超时）。 */
export function registerIntegrationRoutes(ctx, { service }) {
  const HARD_TIMEOUT_MS = 20_000
  ctx.webServer.register({
    kind: 'exact',
    path: `${INTEGRATION_PREFIX}/health`,
    handler: (req, res) => {
      if (!loopbackOnly(req)) return writeJson(res, 403, { ok: false, code: 'loopback-required' })
      writeJson(res, 200, { ok: true, value: healthPayload() })
    },
  })
  ctx.webServer.register({
    kind: 'exact',
    path: `${INTEGRATION_PREFIX}/v1/status`,
    handler: async (req, res) => {
      if (!loopbackOnly(req)) return writeJson(res, 403, { ok: false, code: 'loopback-required' })
      try {
        const value = await Promise.race([
          service.status(),
          new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), HARD_TIMEOUT_MS)),
        ])
        writeJson(res, 200, { ok: true, value })
      } catch (error) {
        writeJson(res, 200, { ok: false, code: 'internal', message: String(error?.message ?? error) })
      }
    },
  })
  return () => {}
}
