/**
 * dsh-bio-graft — hosted-domain integration protocol v2（只读批次）。
 *
 * 契约：`dsh-bio-genie/docs/plugin-integration.md` §2.3（health）/ §2.4（status）/ §3（六态）。
 *   GET {prefix}/health   — 协商端点：身份 + 协议版本 + features。**不 spawn Python、不写盘、不列目录**
 *   GET {prefix}/v1/status — 运行时快照：state / checks[] / generatedAt / data / env / remediations
 *
 * 形状变更史：v0.1 载荷用 `plugin` + `protocol:{major,minors}` + `checks` 对象，
 * 与契约不符 —— 宿主适配器按固定字段名校验，会把 graft 判成 `installed-unavailable`
 * （面板谎报「已安装但不可用」）。v0.1.1 起对齐 v2。
 *
 * 本模块没有 import 期探测：加载插件与提供 /health 绝不 spawn 进程、不修改数据目录。
 */
import { existsSync, readdirSync, statSync } from 'node:fs'
import os from 'node:os'
import { join } from 'node:path'
import { pythonCandidates } from './python.js'
import { PLUGIN_VERSION } from './version.js'
import { EDITORS_SUMMARY } from './editors-summary.js'

export const INTEGRATION_PREFIX = '/api/dsh-bio-graft/integration'
export const PROTOCOL_MAJOR = 1
export const PROTOCOL_MINORS = [0]
export const RUNTIME_PROBE_CACHE_MS = 60_000
export const INTEGRATION_FEATURES = [
  'status',
  'editor-registry',
  'editplans',
  'offtarget-backend',
  'plan-write',
]

const PLUGIN_ID = 'dsh-bio-graft'

function defaultDataRoot() {
  const dshHome = process.env.DSH_HOME ?? join(os.homedir(), '.dsh')
  return join(dshHome, 'dsh-bio-graft')
}

/** 有限条目列表（契约：列表截断 ≤50，其余只给计数）。 */
function listFiles(dir, predicate = () => true) {
  try {
    return readdirSync(dir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && predicate(entry.name))
      .map((entry) => {
        const stat = statSync(join(dir, entry.name))
        return { name: entry.name, sizeBytes: stat.size, modifiedAt: stat.mtime.toISOString() }
      })
      .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
  } catch {
    return []
  }
}

function boundedSummary(dir, predicate) {
  const all = listFiles(dir, predicate)
  return { count: all.length, items: all.slice(0, 50), dir }
}

/** cas-offinder 可执行文件探测（与 python/offtarget.py 的候选顺序一致，仅做路径检查）。 */
function casOffinderProbe(dataRoot) {
  const envPath = process.env.GRAFT_CAS_OFFINDER
  if (envPath && existsSync(envPath)) return { present: true, path: envPath, source: 'GRAFT_CAS_OFFINDER' }
  const local = join(dataRoot, 'bin', 'cas-offinder.exe')
  if (existsSync(local)) return { present: true, path: local, source: 'graft-bin' }
  const sibling = join(process.cwd(), 'python', 'cas-offinder.exe')
  if (existsSync(sibling)) return { present: true, path: sibling, source: 'plugin-python-dir' }
  return {
    present: false,
    path: null,
    source: null,
    install_hint: '跑 graft_backend_status(action="ensure") 自动获取 BSD-3 官方二进制（仅 Windows），'
      + '或手动放置到 ~/.dsh/dsh-bio-graft/bin/',
  }
}

/** 解释器候选链（与 src/python.js 同源；只做路径存在性判断，不 spawn）。 */
function interpreterProbe() {
  const candidates = pythonCandidates().map((c) => ({
    path: c.path,
    source: c.source,
    exists: c.path === 'python' ? null : existsSync(c.path),
  }))
  const hosted = candidates.find((c) => c.exists === true)
  const selected = hosted ?? candidates.find((c) => c.path === 'python') ?? null
  return { selected, candidates }
}

function loopbackOnly(req) {
  const sa = req.socket?.remoteAddress ?? ''
  const loopbackIp = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(sa)
  if (!loopbackIp) return false
  try {
    const host = (req.headers?.host ?? '').split(':')[0]
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(host)) return false
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
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(body, null, 2))
}

function statusCheck(id, status, detail) {
  return { id, status, detail }
}

/**
 * 运行时服务（status 有 60s 缓存；health 每次现取但值恒定）。
 * 返回值一律是**信封**：{ ok: true, value: {...} } —— 与宿主解析器（以及 gem）一致。
 */
export function createIntegrationService() {
  let cached = null
  let cachedAt = 0

  return {
    async health() {
      return {
        ok: true,
        value: {
          pluginId: PLUGIN_ID,
          pluginVersion: PLUGIN_VERSION,
          protocolMajor: PROTOCOL_MAJOR,
          protocolMinors: PROTOCOL_MINORS,
          features: INTEGRATION_FEATURES,
        },
      }
    },

    async status() {
      if (cached && (Date.now() - cachedAt) < RUNTIME_PROBE_CACHE_MS) return cached
      const dataRoot = defaultDataRoot()
      const plansDir = join(dataRoot, 'plans')
      const plansDirExists = existsSync(plansDir)
      const dataRootExists = existsSync(dataRoot)
      const plans = listFiles(plansDir, (n) => n.endsWith('.editplan.json'))
      const backend = casOffinderProbe(dataRoot)
      const interp = interpreterProbe()

      const checks = [
        statusCheck(
          'python.interpreter',
          interp.selected && interp.selected.exists === true ? 'ok'
            : (interp.selected ? 'warn' : 'missing'),
          interp.selected
            ? `${interp.selected.path}（source=${interp.selected.source}）`
            : '未找到可用解释器：设置 GRAFT_PYTHON，或让宿主 dsh-bio-genie 完成自举环境安装',
        ),
        statusCheck(
          'runtime.casoffinder',
          backend.present ? 'ok' : 'missing',
          backend.present
            ? `${backend.path}（source=${backend.source}）`
            : (backend.install_hint ?? '未安装 cas-offinder'),
        ),
        statusCheck(
          'plans.dir',
          (plansDirExists || dataRootExists) ? 'ok' : 'warn',
          plansDirExists
            ? `${plansDir}（${plans.length} 个计划）`
            : `尚未创建（首次 graft_plan_save 自动创建）：${plansDir}`,
        ),
      ]

      const value = {
        ok: true,
        value: {
          state: checks.every((c) => c.status === 'ok') ? 'ready' : 'degraded',
          generatedAt: new Date().toISOString(),
          pluginVersion: PLUGIN_VERSION,
          features: INTEGRATION_FEATURES,
          checks,
          data: {
            plans: boundedSummary(plansDir, (n) => n.endsWith('.editplan.json')),
            editors: EDITORS_SUMMARY,
            backend: { casOffinder: { present: backend.present, path: backend.path ?? null } },
          },
          env: {
            interpreter: interp.selected
              ? { selected: interp.selected.path, source: interp.selected.source,
                  candidates: interp.candidates }
              : { selected: null, candidates: interp.candidates },
          },
          remediations: checks
            .filter((c) => c.status !== 'ok')
            .map((c) => ({
              code: c.id === 'runtime.casoffinder'
                ? 'graft.ensure-offtarget-backend'
                : c.id === 'python.interpreter'
                  ? 'graft.set-python-interpreter'
                  : 'graft.inspect-runtime',
              owner: 'graft',
              detail: `${c.id}: ${c.detail}`,
            })),
        },
      }
      cached = value
      cachedAt = Date.now()
      return value
    },

    invalidate() {
      cached = null
      cachedAt = 0
    },
  }
}

/** 注册 integration 路由（loopback-only 守卫 + status 20s 硬超时）。 */
export function registerIntegrationRoutes(ctx, { service }) {
  const HARD_TIMEOUT_MS = 20_000
  const disposers = []

  const respond = async (res, producer) => {
    try {
      writeJson(res, 200, await producer())
    } catch (error) {
      // 契约：任何未预期异常也要返回 JSON 信封（前端永远拿到 JSON）
      writeJson(res, 200, { ok: false, code: 'internal', message: String(error?.message ?? error) })
    }
  }

  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: `${INTEGRATION_PREFIX}/health`,
    handler: (req, res) => {
      if (!loopbackOnly(req)) return writeJson(res, 403, { ok: false, code: 'loopback-required' })
      return respond(res, () => service.health())
    },
  }))

  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: `${INTEGRATION_PREFIX}/v1/status`,
    handler: (req, res) => {
      if (!loopbackOnly(req)) return writeJson(res, 403, { ok: false, code: 'loopback-required' })
      return respond(res, () => Promise.race([
        service.status(),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), HARD_TIMEOUT_MS)),
      ]))
    },
  }))

  return () => disposers.forEach((d) => d?.())
}
