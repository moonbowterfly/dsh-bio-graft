// test/validation.mjs — 验证方案（ValidationRequirement[]）黄金断言。
//
// 契约（GPT 裁决 #11/#18 + 用户两层生成契约）：
//   · 分档 required / recommended / conditional，每条含 question + why（不许空理由）
//   · 模态差异：碱基编辑必查 bystander 与全产物谱；HDR 必查双侧连接点；双 guide 缺失必查连接点/长度/区段缺失
//   · 宿主差异：植物额外出现嵌合/合子性等；cell_line 不得出现植物项
//   · **EditOutcomeMetrics 必须带分子/分母/assay**（禁止裸 efficiency）
//   · 两层生成契约 + cannot_conclude 必须显式
import { check, summary, op } from './harness.mjs'

const ko = op('validation_plan', { modality: 'nuclease_ko' })
check('tiers are three arrays with rationale on every row',
  Array.isArray(ko.required) && Array.isArray(ko.recommended) && Array.isArray(ko.conditional) &&
  [...ko.required, ...ko.recommended, ...ko.conditional]
    .every((r) => r.id && r.question && r.why && r.zh),
  JSON.stringify(ko.required?.map((r) => r.id)))
check('nuclease KO requires on-target amplicon + allele composition',
  ko.required.some((r) => r.id === 'on_target_amplicon') &&
  ko.required.some((r) => r.id === 'allele_composition'),
  JSON.stringify(ko.required.map((r) => r.id)))
check('nuclease KO mentions the protein-level caveat (frameshift ≠ no protein)',
  [...ko.required, ...ko.recommended].some((r) => r.id === 'protein_level_knockout' &&
    /截短体|重新起始/.test(r.why)))
check('primer handoff points at genie instead of reimplementing primer design',
  /bio_primer3_design/.test(String(ko.handoff_summary?.primers)))

const be = op('validation_plan', { modality: 'base_edit' })
check('base editing requires bystander quantification + outcome spectrum + indel fraction',
  ['bystander_quantification', 'outcome_spectrum', 'indel_fraction']
    .every((id) => be.required.some((r) => r.id === id)),
  JSON.stringify(be.required.map((r) => r.id)))
check('base editing warns not to report a single "editing efficiency"',
  be.notes.some((n) => /bystander/.test(n)))

const del = op('validation_plan', { modality: 'deletion_pair' })
check('deletion pair requires junction PCR + size verification + absence of deleted segment',
  ['junction_pcr', 'deletion_size_verification', 'absence_of_deleted_segment']
    .every((id) => del.required.some((r) => r.id === id)),
  JSON.stringify(del.required.map((r) => r.id)))

const hdr = op('validation_plan', { modality: 'hdr' })
check('HDR requires both junctions + internal edit + WT discrimination',
  ['both_junctions', 'internal_intended_edit', 'wildtype_allele_discrimination']
    .every((id) => hdr.required.some((r) => r.id === id)),
  JSON.stringify(hdr.required.map((r) => r.id)))

// ── 宿主差异 ──────────────────────────────────────────────────────────────
const plant = op('validation_plan', { modality: 'nuclease_ko', host_type: 'plant', delivery: 'dna' })
check('plant host adds mosaicism + zygosity to REQUIRED (host_specific flagged)',
  ['mosaicism_chimerism', 'zygosity'].every((id) =>
    plant.required.some((r) => r.id === id && r.host_specific === 'plant')),
  JSON.stringify(plant.required.map((r) => r.id)))
check('plant host adds heritable transmission to RECOMMENDED',
  plant.recommended.some((r) => r.id === 'heritable_transmission'),
  JSON.stringify(plant.recommended.map((r) => r.id)))
check('cell_line plan contains no plant-specific rows',
  !ko.required.concat(ko.recommended, ko.conditional).some((r) => r.host_specific),
  JSON.stringify(ko.required.concat(ko.recommended, ko.conditional).map((r) => r.host_specific)))
check('plant + DNA delivery warns about transgene/vector persistence',
  plant.notes.some((n) => /残留/.test(n)), JSON.stringify(plant.notes))

// ── 指标定义（禁止裸 efficiency）───────────────────────────────────────────
check('every outcome metric carries numerator + denominator + assay',
  Array.isArray(ko.outcome_metrics) && ko.outcome_metrics.length >= 6 &&
  ko.outcome_metrics.every((m) => m.metric && m.numerator && m.denominator && m.assay),
  JSON.stringify(ko.outcome_metrics?.slice(0, 3).map((m) => m.metric)))
check('the purity-vs-rate denominator difference is spelled out',
  ko.outcome_metrics.some((m) => m.metric === 'product_purity' && /分母/.test(String(m.note))) &&
  /分母不同/.test(String(ko.metrics_note)))
check('no bare "efficiency" metric exists',
  !ko.outcome_metrics.some((m) => m.metric === 'efficiency'))

// ── 诚实边界与两层契约 ────────────────────────────────────────────────────
check('cannot_conclude states: no efficiency prediction, no safety conclusion',
  ko.cannot_conclude.some((s) => /不能预测编辑效率/.test(s)) &&
  ko.cannot_conclude.some((s) => /不能给出「安全」结论/.test(s)),
  JSON.stringify(ko.cannot_conclude?.slice(0, 2)))
check('two-layer generation contract is explicit (required tier is non-deletable)',
  typeof ko.generation_contract?.layer1_facts === 'string' &&
  ko.generation_contract.layer1_facts.length > 10 &&
  /不可删/.test(String(ko.generation_contract?.layer2_agent)) &&
  /\[推断\]/.test(String(ko.generation_contract?.layer2_agent)),
  JSON.stringify(ko.generation_contract).slice(0, 240))

// ── 写入 EditPlan 的闭环 ──────────────────────────────────────────────────
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdirSync, rmSync } from 'node:fs'
const dir = join(tmpdir(), `graft-valid-${process.pid}`)
rmSync(dir, { recursive: true, force: true })
mkdirSync(dir, { recursive: true })
const created = op('plan_create', {
  plan_dir: dir, plan_name: 'valid_test', action: 'new',
  intent: { target: 'x', desired_change: 'knockout', modality: 'nuclease_ko' },
  reference: { sequence_hash: 'sha256:test' },
})
op('plan_create', { plan_dir: dir, plan_name: 'valid_test', action: 'add_run', validation_plan: be })
const loaded = op('plan_load', { plan_path: created.plan_path })
const runWithPlan = (loaded.runs ?? []).find((r) => r.content?.validation_plan)
check('the validation plan is recorded into the EditPlan run ledger',
  Boolean(runWithPlan) &&
  runWithPlan.content.validation_plan.modality === 'base_edit' &&
  runWithPlan.content.validation_plan.required.some((r) => r.id === 'bystander_quantification'),
  JSON.stringify((runWithPlan?.content?.validation_plan?.required ?? []).map((r) => r.id)))
rmSync(dir, { recursive: true, force: true })

// ── 输入卫生 ──────────────────────────────────────────────────────────────
let badMod = ''
try { op('validation_plan', { modality: 'magic' }) } catch (e) { badMod = e.message }
check('unknown modality fails loudly and lists the known ones',
  /unknown modality/.test(badMod) && /base_edit/.test(badMod), badMod.slice(0, 140))

summary('validation')
