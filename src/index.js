// dsh-bio-graft — Cordis 插件主模块
// 注入 tools（6 个 v0.1 语义化工具）+ skills（graft-expert）+ 可选 webServer 的 integration 路由。
// 形态与 dsh-bio-gem 一致：宿主（dsh-bio-genie）通过 integration v1 消费本插件状态。
import { registerTools } from './tools.js'
import { registerSkills } from './skills.js'
import { registerIntegrationRoutes, createIntegrationService } from './integration.js'

/** Cordis 插件名（cordis.patch.yml row id 同名）。 */
export const name = 'dsh-bio-graft'

/**
 * 静态注入只列必选服务（数组形式是 cordis 唯一支持的「服务名列表」写法；
 * `{required, optional}` 对象形式会让插件永远 pending —— 实测过）。
 * `webServer` 是可选服务，apply 内动态注入。
 */
export const inject = ['tools', 'skills']

/**
 * 装配插件。
 * @param {import('@deepseek-ai/cordis').Context} ctx
 */
export function apply(ctx) {
  registerTools(ctx)
  registerSkills(ctx)

  const service = createIntegrationService()
  ctx.inject(['webServer'], (webCtx) => {
    webCtx.effect(() => registerIntegrationRoutes(webCtx, { service }),
      'dsh-bio-graft: integration API routes')
    const warmup = setTimeout(() => { void service.status().catch(() => {}) }, 8_000)
    webCtx.effect(() => () => clearTimeout(warmup), 'dsh-bio-graft: runtime probe warm-up')
  })
}
