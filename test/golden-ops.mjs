// test/golden-ops.mjs — 黄金 op 断言（人工可算的固定夹具；期望值全部写死，不做模糊匹配）
//
// 覆盖：FASTA/多行输入(D1) · Cas12a IUPAC PAM(D2) · cut_site 坐标口径(D5) · EditPlan 账本(D6)
// 夹具设计：序列里只有一个 PAM 命中，且反链无命中 —— 期望值可手算。
import { check, summary, op } from './harness.mjs'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// 夹具 1（SpCas9）：TTTT + spacer(20) + AGG + CCCC，全序列无第二个 GG 二核苷酸
//   位置: 0-3 filler | 4..24 spacer | 24..27 PAM(AGG) | 27..31 filler
//   唯一候选：start_0=4, end_0=27；SpCas9 平末端切点 = PAM 起点上游 3 bp → cut_site_0=21
const SPCAS9_TARGET = 'TTTTACGTACGTACGTACGTACGTAGGCCCC'

// 夹具 2（Cas12a）：TTTA(5'PAM) + spacer(20) + GGGG，全序列无第二个 TTTV
//   唯一候选：start_0=0, end_0=24；5' PAM 口径：cut_site_0 = PAM 起点 + cut_offset(18)
const CAS12A_TARGET = 'TTTACGTACGTACGTACGTACGTGGGG'

// ---------- 1. FASTA 输入（D1）----------
const fasta = `>demo_construct synthetic test loci\n${SPCAS9_TARGET}\n`
let fromFasta = null
let fastaError = null
try {
  fromFasta = op('guide_enumerate', { sequence: fasta, editor: 'SpCas9', top_n: 10 })
} catch (e) {
  fastaError = e.message
}
check('FASTA input yields candidates (D1)', fromFasta !== null && fromFasta.n_candidates_raw >= 1,
  fastaError ? fastaError.slice(0, 200) : `n_candidates_raw=${fromFasta?.n_candidates_raw}`)
check('FASTA input records the record id (D1)', fromFasta?.record_id === 'demo_construct',
  `record_id=${fromFasta?.record_id}`)

const fromRaw = op('guide_enumerate', { sequence: SPCAS9_TARGET, editor: 'SpCas9', top_n: 10 })
check('FASTA input === raw input (identical candidates)',
  fromFasta !== null && JSON.stringify(fromFasta.candidates) === JSON.stringify(fromRaw.candidates))

// ---------- 2. 多行裸序列 ----------
const multiline = `${SPCAS9_TARGET.slice(0, 12)}\n${SPCAS9_TARGET.slice(12)}\n`
const fromMultiline = op('guide_enumerate', { sequence: multiline, editor: 'SpCas9', top_n: 10 })
check('multi-line raw sequence tolerated',
  fromMultiline.n_candidates_raw === fromRaw.n_candidates_raw,
  `${fromMultiline.n_candidates_raw} vs ${fromRaw.n_candidates_raw}`)

// ---------- 3. SpCas9 单候选坐标与切割位点（D5）----------
const plus = fromRaw.candidates.filter((c) => c.strand === '+')
check('SpCas9 fixture has exactly one + strand candidate', plus.length === 1, `got ${plus.length}`)
if (plus.length === 1) {
  const c = plus[0]
  check('spacer sequence', c.protospacer === 'ACGTACGTACGTACGTACGT', c.protospacer)
  check('PAM', c.pam === 'AGG', c.pam)
  check('start_0/end_0 half-open incl. PAM', c.start_0 === 4 && c.end_0 === 27,
    `${c.start_0}/${c.end_0}`)
  check('cut_site_0 = PAM start - 3 (D5)', c.cut_site_0 === 21, `got ${c.cut_site_0}`)
  check('cut_site_convention is machine-readable (D5)',
    typeof c.cut_site_convention === 'string' && c.cut_site_convention.length > 0)
  check('cut_site_verified is a boolean (D5)', typeof c.cut_site_verified === 'boolean')
}

// ---------- 4. Cas12a / IUPAC PAM（D2）----------
const cas12a = op('guide_enumerate', { sequence: CAS12A_TARGET, editor: 'Cas12a', top_n: 10 })
check('Cas12a TTTV PAM matches (D2)', cas12a.n_candidates_raw >= 1,
  `n_candidates_raw=${cas12a.n_candidates_raw} (was 0 before the IUPAC fix)`)
const casPlus = cas12a.candidates.filter((c) => c.strand === '+')
if (casPlus.length >= 1) {
  const c = casPlus[0]
  check('Cas12a PAM captured literally', c.pam === 'TTTA', c.pam)
  check('Cas12a spacer coordinates', c.start_0 === 0 && c.end_0 === 24, `${c.start_0}/${c.end_0}`)
  check('Cas12a cut_site_0 follows 5prime convention (D5)', c.cut_site_0 === 18, `got ${c.cut_site_0}`)
}

// ---------- 5. 未编辑器必须响亮失败（不许静默给空候选）----------
let unknownEditorThrew = false
try {
  op('guide_enumerate', { sequence: SPCAS9_TARGET, editor: 'NoSuchEditor' })
} catch (e) {
  unknownEditorThrew = /unknown editor/i.test(e.message)
}
check('unknown editor fails loudly', unknownEditorThrew)

// ---------- 6. EditPlan 账本（D6）----------
const planDir = join(tmpdir(), `graft-golden-plans-${process.pid}`)
rmSync(planDir, { recursive: true, force: true })
mkdirSync(planDir, { recursive: true })

const created = op('plan_create', {
  plan_dir: planDir,
  plan_name: 'golden_fixture',
  action: 'new',
  intent: { target: 'fixture', desired_change: 'knockout', modality: 'nuclease' },
})
check('plan_create returns run_number 1', created.run_number === 1, `got ${created.run_number}`)

// 删掉 001 后再追加：旧实现用「文件数 + 1」会撞号重写历史，新实现必须取 max+1
rmSync(created.run_file, { force: true })
const second = op('plan_create', {
  plan_dir: planDir, plan_name: 'golden_fixture', action: 'add_run', provenance: { note: 'second' },
})
check('add_run after deleting run 001 does not collide (D6)', second.run_number === 2,
  `got ${second.run_number}`)

const loaded = op('plan_load', { plan_path: created.plan_path })
check('plan_load returns runs timeline (D6)', Array.isArray(loaded.runs) && loaded.n_runs >= 1,
  `n_runs=${loaded.n_runs}`)
const byName = op('plan_load', { plan_path: created.plan_path })
check('plan_load reads the plan back', byName.plan?.plan_name === 'golden_fixture')

// 同名保护（A7 起生效）：再次 new 必须报错而不是覆盖历史
let clobberBlocked = false
try {
  op('plan_create', { plan_dir: planDir, plan_name: 'golden_fixture', action: 'new' })
} catch (e) {
  clobberBlocked = /already exists|已存在/.test(e.message)
}
check('plan_create(new) refuses to clobber an existing plan (D6)', clobberBlocked)

rmSync(planDir, { recursive: true, force: true })
summary('golden-ops')
