// skills.js — dsh-bio-graft skill 注册（v0.1：graft-expert 主 skill）
// 参考 dsh-bio-genie / gem 的 ctx.skills.register 同款模式。
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SKILLS_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'skills')

export function registerSkills(ctx) {
  const disposers = []
  let content = ''
  try {
    content = readFileSync(join(SKILLS_DIR, 'graft-expert.md'), 'utf8')
  } catch {
    content = 'Skill body missing from plugin package (skills/graft-expert.md)。'
  }
  disposers.push(ctx.skills.register({
    name: 'graft-expert',
    description:
      '基因编辑设计主指引：工具分层选择（graft_profiles/design/score/offtarget/plan_save/plan_load）、'
      + '编辑生命周期工作流（TARGET→DESIGN→RANK→VERIFY→AUDIT）、EditPlan 账本哲学、'
      + '脱靶铁律（永远不说 safe）、风险分级门控、安全边界。',
    whenToUse: '设计 sgRNA/CRISPR/碱基编辑方案、评估脱靶风险、保存编辑计划时。',
  }))
  ctx.effect(() => () => disposers.forEach((d) => d?.()), 'dsh-bio-graft: skills disposal')
}
