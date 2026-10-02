// test/integration-contract.mjs — hosted-domain integration 协议 v2 形状断言。
//
// 契约文档：D:/Program/Github/dsh-bio-genie/docs/plugin-integration.md §2.3（health）/§2.4（status）
// 为什么要有这个文件：宿主 genie 的六态适配器按固定字段名与 checks 数组校验；载荷形状不对
// 时 graft 会被判成 installed-unavailable（面板谎报「已安装但不可用」）。
//
// 本测试不需要起 HTTP 服务：直接调 createIntegrationService()，并用 mock 捕获路由。
// ⚠️ editors 静态摘要与 python/editors.py 的**漂移**也在这里用真实 op 比对（单一事实源在 Python 侧）。
import './register-dsh-tools.mjs'
import { readFileSync } from 'node:fs'
import { check, summary, op } from './harness.mjs'
import { captureRoutes, invokeRoute } from './fixtures/integration-route-harness.mjs'
import { createIntegrationService, registerIntegrationRoutes, INTEGRATION_PREFIX,
  INTEGRATION_FEATURES, PROTOCOL_MAJOR, PROTOCOL_MINORS }
  from '../src/integration.js'
import { PLUGIN_VERSION } from '../src/version.js'

const svc = createIntegrationService()
const health = await svc.health()
const status = await svc.status()
const capabilities = await svc.capabilities()
const manifest = JSON.parse(readFileSync(new URL('../capabilities.json', import.meta.url), 'utf8'))

// ---------- §2.3 health（协商端点：静态、快、无副作用）----------
check('health returns the {ok:true, value:{...}} envelope',
  health?.ok === true && typeof health.value === 'object')
check('health uses the contract field names (pluginId/pluginVersion/protocolMajor/protocolMinors/features)',
  typeof health.value.pluginId === 'string' &&
  health.value.pluginId === 'dsh-bio-graft' &&
  typeof health.value.pluginVersion === 'string' &&
  health.value.protocolMajor === PROTOCOL_MAJOR &&
  Array.isArray(health.value.protocolMinors) &&
  health.value.protocolMinors.join(',') === PROTOCOL_MINORS.join(',') &&
  Array.isArray(health.value.features),
  JSON.stringify(health.value).slice(0, 240))
check('health pluginVersion is read from package.json (single source)',
  health.value.pluginVersion === PLUGIN_VERSION, `${health.value.pluginVersion} vs ${PLUGIN_VERSION}`)
check('health carries no probe results (no python spawn, no dataRoot dump)',
  health.value.checks === undefined && health.value.data === undefined)
check('health advertises capabilities',
  health.value.features.includes('capabilities'))
check('health features match shipped capabilities manifest',
  JSON.stringify(health.value.features) === JSON.stringify(manifest.integration.features))

// ---------- §2.4 status（运行时快照）----------
const v = status.value
check('status returns the envelope', status?.ok === true && typeof v === 'object')
check('status.state ∈ {ready, degraded}', ['ready', 'degraded'].includes(v.state), v.state)
check('status.checks is an ARRAY of {id,status,detail}',
  Array.isArray(v.checks) && v.checks.every((c) =>
    typeof c.id === 'string' && ['ok', 'warn', 'missing', 'error'].includes(c.status) &&
    typeof c.detail === 'string'),
  JSON.stringify(v.checks).slice(0, 240))
check('status carries the three required check ids',
  ['python.interpreter', 'runtime.casoffinder', 'plans.dir'].every((id) =>
    v.checks.some((c) => c.id === id)),
  v.checks.map((c) => c.id).join(','))
check('state is consistent with checks',
  v.state === (v.checks.some((c) => c.status !== 'ok') ? 'degraded' : 'ready'))
check('status has generatedAt ISO8601', /^\d{4}-\d{2}-\d{2}T/.test(v.generatedAt ?? ''), v.generatedAt)
check('status echoes features + pluginVersion', Array.isArray(v.features) && v.pluginVersion === PLUGIN_VERSION)
check('status advertises capabilities for host conditional fetch',
  v.features.includes('capabilities'))
check('status.data.plans has count + bounded items + dir',
  typeof v.data?.plans?.count === 'number' && Array.isArray(v.data.plans.items) &&
  v.data.plans.items.length <= 50 && typeof v.data.plans.dir === 'string')
check('status.data.backend reports the cas-offinder binary',
  typeof v.data?.backend?.casOffinder?.present === 'boolean')
check('status.env exposes the interpreter selection chain',
  v.env?.interpreter === null ||
  (typeof v.env?.interpreter?.selected === 'string' ||
   (v.env?.interpreter?.selected === null && Array.isArray(v.env?.interpreter?.candidates))),
  JSON.stringify(v.env).slice(0, 200))
check('remediations carry controlled codes + owner ∈ {genie, graft}',
  Array.isArray(v.remediations) &&
  v.remediations.every((r) => typeof r.code === 'string' &&
    (r.owner === 'genie' || r.owner === 'graft') && typeof r.detail === 'string'),
  JSON.stringify(v.remediations).slice(0, 200))
check('no remediation is emitted for an ok check',
  v.checks.filter((c) => c.status === 'ok')
    .every((c) => !v.remediations.some((r) => r.detail.includes(c.id))))

// ---------- editors 静态摘要必须与 python/editors.py 一致（防漂移）----------
const pyProfiles = op('profile_list', {})
const pyByName = new Map(pyProfiles.editors.map((e) => [e.name, e]))
check('status.data.editors covers exactly the Python registry',
  Array.isArray(v.data?.editors) &&
  v.data.editors.length === pyByName.size &&
  v.data.editors.every((e) => pyByName.has(e.name)),
  `js=${(v.data?.editors ?? []).map((e) => e.name).join(',')} | py=${[...pyByName.keys()].join(',')}`)
for (const e of v.data?.editors ?? []) {
  const py = pyByName.get(e.name)
  if (!py) continue
  check(`editor ${e.name} static summary matches the Python profile`,
    e.pam === py.pam && e.pamSide === py.pam_side && e.spacerLength === py.spacer_length &&
    e.verified === py.verified,
    `js=${JSON.stringify(e)} py=${JSON.stringify({ pam: py.pam, pam_side: py.pam_side, spacer_length: py.spacer_length, verified: py.verified })}`)
}

// ---------- 缓存语义：status 有 TTL 缓存，invalidate 后重取 ----------
const again = await svc.status()
check('status is cached within the TTL (same generatedAt)', again.value.generatedAt === v.generatedAt)
svc.invalidate()
const fresh = await svc.status()
check('invalidate() forces a fresh probe', fresh.value.generatedAt !== undefined)

// ---------- /v1/capabilities：随包 manifest、实际工具注册、HTTP 路由一致 ----------
const cv = capabilities.value
check('capabilities uses the host contract envelope and version',
  capabilities.ok === true && cv?.contract_version === '1' &&
  cv.plugin_id === manifest.pluginId && cv.plugin_version === PLUGIN_VERSION)
check('capabilities count and names come from shipped manifest',
  cv.tool_count === manifest.tools.length &&
  JSON.stringify(cv.tools.map((tool) => tool.name)) === JSON.stringify(manifest.tools) &&
  new Set(manifest.tools).size === manifest.tools.length)

const toolsMod = await import('../src/tools.js') // import failure is a test failure
const registered = []
toolsMod.registerTools({
  tools: { register: (tool) => { registered.push(tool.name); return () => {} } },
  effect: () => () => {},
})
check('capabilities manifest matches actual registered tools',
  registered.length === manifest.tools.length &&
  registered.slice().sort().join(',') === manifest.tools.slice().sort().join(','))

const { routes, dispose } = captureRoutes(registerIntegrationRoutes, svc)
const capabilitiesRoute = routes.find((route) =>
  route.kind === 'exact' && route.path === manifest.integration.capabilitiesPath)
check('capabilities route is registered at the advertised path',
  capabilitiesRoute?.path === `${INTEGRATION_PREFIX}/v1/capabilities`)
if (capabilitiesRoute) {
  const local = await invokeRoute(capabilitiesRoute)
  check('loopback GET /v1/capabilities returns the service payload',
    local.statusCode === 200 && JSON.stringify(local.body) === JSON.stringify(capabilities))
  const remote = await invokeRoute(capabilitiesRoute, { remoteAddress: '192.0.2.1' })
  check('remote GET /v1/capabilities is rejected',
    remote.statusCode === 403 && remote.body?.code === 'loopback-required')
  const post = await invokeRoute(capabilitiesRoute, { method: 'POST' })
  check('POST /v1/capabilities is rejected',
    post.statusCode === 405 && post.body?.code === 'method-not-allowed')
}
dispose()

summary('integration-contract')
