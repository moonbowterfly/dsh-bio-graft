// skills.js — dsh-bio-graft skill 注册（v0.1：graft-expert 主 skill）
// 工具选择决策树 + 工作流 + 硬规则；遵循 dsh-bio-genie/gem 注册模式（ctx.skills.register）。
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
      '基因编辑设计主指引：工具分层选择（graft_profiles/design/score/rank/offtarget/base_edit/strategy/validation_plan/plan_save/plan_load）、'
      + '编辑生命周期工作流（TARGET→DESIGN→RANK→STRATEGY→VERIFY→AUDIT）与 modality 判定（nuclease / 碱基编辑 / 多 guide 缺失 / 尚未支持的 PE-HDR-CRISPRi 如实说明）、验证方案分档（required 不可删 + 指标定义）、'
      + 'score vector 哲学（禁止综合分；排名由 graft_rank 按声明策略完成并落账本）、负证据语义（0/null/not_searched 必须区分）、'
      + '碱基编辑硬约束（窗口编号口径 + bystander 必须写明）、'
      + 'EditPlan 账本、脱靶铁律（永不说 safe）、风险分级门控（Level 0-3）、安全边界。',
    whenToUse:
      '设计 sgRNA/CRISPR 敲除敲入、碱基编辑、prime editing、脱靶评估、'
      + 'HDR 供体设计、编辑验证方案、保存/读回编辑计划等需求时。',
    source: 'custom',
    provider: 'dsh-bio-graft',
    content,
  }))
  return () => disposers.forEach((d) => d())
}
