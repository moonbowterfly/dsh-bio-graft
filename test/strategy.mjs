// test/strategy.mjs — EditStrategy（多 guide 几何）黄金夹具（人工可算）。
//
// 契约（GPT 裁决 #6/#16）：
//   · 多 guide 不是 Guide[]：几何（切点→缺失区间/junction/移码/PAM 朝向）+ 组合事实（两两脱靶）
//   · **pairwise 不是把两条 guide 的风险相加**；数据缺失 = not_searched（负证据语义）
//   · 未实现的策略（prime_edit / hdr / multiplex…）显式 implemented:false + cannot_design
//     —— 不许给出看似可行的假设计
import { check, summary, op } from './harness.mjs'

// 强一些的伪随机 filler（早期版本用 LCG 低比特 → 退化成 'ACGT' 周期串，夹具失效）
function filler(n, seed) {
  let s = ''
  let x = seed >>> 0
  for (let i = 0; i < n; i += 1) {
    x ^= x << 13; x >>>= 0
    x ^= x >>> 17
    x ^= x << 5; x >>>= 0
    s += 'ACGT'[(x >>> 16) & 3]
  }
  return s
}

// 序列布局（140 nt）：
//   0..32 filler | 33..52 spacer1(+链) | 53..55 PAM1=AGG | 56..83 filler
//   84..86 'CCT' ← 反链 guide 的 + 链 PAM 区（反链 frame 读到 'AGG'）| 87..106 spacer2 | 107..139 filler
// 期望：guide1 '+' cut = 53-3 = 50；guide2 '−' cut = 87+3 = 90
//       → 缺失区间 [50, 90)，长度 40 bp（40 % 3 = 1 → 移码）
const SP1 = filler(20, 111)
const SP2 = filler(20, 222)
const SEQ = filler(33, 333) + SP1 + 'AGG' + filler(28, 444) + 'CCT' + SP2 + filler(33, 555)
const REGION = [50, 90]

const scan = op('guide_enumerate', { sequence: SEQ, editor: 'SpCas9', top_n: 1000 })
const cands = scan.candidates ?? []
const revcomp = (s) => s.split('').reverse().map((c) => ({ A: 'T', C: 'G', G: 'C', T: 'A' }[c])).join('')
const SP2_RC = revcomp(SP2)
// 注意：反链候选的 protospacer 是**反链 frame 的序列**（= +链该区的反向互补），不是 +链序列本身
const g1 = cands.find((c) => c.protospacer === SP1 && c.strand === '+')
const g2 = cands.find((c) => c.protospacer === SP2_RC && c.strand === '-')
check('fixture: both designed guides are found with the expected cut sites',
  g1?.cut_site_0 === 50 && g2?.cut_site_0 === 90,
  `g1=${g1?.cut_site_0} g2=${g2?.cut_site_0} (n_candidates=${cands.length})`)
check('fixture: strands are + and − respectively',
  g1?.strand === '+' && g2?.strand === '-', `${g1?.strand}/${g2?.strand}`)

const CG = { candidates: cands, region_start_0: REGION[0], region_end_0: REGION[1], cds_start_0: 0 }

// ── ① deletion_pair：缺失区间 / 长度 / 移码 ────────────────────────────────
const del = op('evaluate_strategy', { ...CG, strategy: 'deletion_pair' })
const pair = (del.pairs ?? []).find((p) =>
  p.left.protospacer === SP1 && p.right.protospacer === SP2_RC)
check('deletion_pair: the designed pair is predicted with the exact deleted interval',
  pair && JSON.stringify(pair.deleted_interval_0based_half_open) === JSON.stringify(REGION) &&
  pair.deleted_size_bp === 40,
  JSON.stringify(pair && { iv: pair.deleted_interval_0based_half_open, size: pair.deleted_size_bp }))
check('deletion_pair: the pair covers the declared region',
  pair?.covers_declared_region === true, JSON.stringify(pair?.reject_reason))
check('deletion_pair: covering is "cuts flank the region", with the outside-deletion cost reported',
  pair?.extra_deleted_bp_outside_region === 0,
  JSON.stringify({ extra: pair?.extra_deleted_bp_outside_region }))
check('deletion_pair: non-covering pairs are rejected and counted (not silently mixed in)',
  typeof del.n_pairs_rejected_not_covering === 'number' &&
  del.n_pairs_rejected_not_covering >= 1 &&
  (del.pairs ?? []).every((p) => p.covers_declared_region === true),
  JSON.stringify({ rejected: del.n_pairs_rejected_not_covering, returned: (del.pairs ?? []).length }))
check('deletion_pair: pairs are sorted by "least extra deletion outside the region" first',
  (del.pairs ?? []).every((p, i, arr) => i === 0 ||
    (arr[i - 1].extra_deleted_bp_outside_region ?? 0) <= (p.extra_deleted_bp_outside_region ?? 0)),
  JSON.stringify((del.pairs ?? []).slice(0, 5).map((p) => p.extra_deleted_bp_outside_region)))
check('deletion_pair: frameshift computed from the declared CDS (40 % 3 !== 0)',
  pair?.in_frame === false && /移码/.test(String(pair?.frameshift_note)),
  JSON.stringify({ in_frame: pair?.in_frame }))
check('deletion_pair: junction rule is stated (no hidden assumptions)',
  /预测连接点/.test(String(pair?.junction_rule)))
check('deletion_pair: geometry-only discipline is stated',
  /只给几何与组合事实/.test(String(del.geometry_only)) && /不预测/.test(String(del.geometry_only)))

// ── ② pairwise 脱靶：无数据必须 not_searched（不是「无风险」）──────────────
check('pairwise off-target without hit data → not_searched + missing list',
  pair?.offtarget_pairwise?.status === 'not_searched' &&
  (pair.offtarget_pairwise.missing ?? []).length === 2 &&
  /不得当「无风险」/.test(String(pair.offtarget_pairwise.note)),
  JSON.stringify(pair?.offtarget_pairwise))

// ── ③ pairwise 脱靶：给了 hits 才算，且只算同染色体、按距离排序 ────────────
const withHits = cands.map((c) => {
  if (c.protospacer === SP1) {
    return { ...c, offtarget_hits: [
      { chromosome: 'chrX', position_0based: 1000, mismatches: 2 },
      { chromosome: 'chrY', position_0based: 5, mismatches: 3 },       // 不同染色体 → 不计
    ] }
  }
  if (c.protospacer === SP2_RC) {
    return { ...c, offtarget_hits: [
      { chromosome: 'chrX', position_0based: 1850, mismatches: 3 },    // 同染色、距 850
      { chromosome: 'chrX', position_0based: 9300, mismatches: 3 },    // 同染色、距 8300
    ] }
  }
  return c
})
const del2 = op('evaluate_strategy', { ...CG, candidates: withHits, strategy: 'deletion_pair' })
const pair2 = (del2.pairs ?? []).find((p) => p.left.protospacer === SP1 && p.right.protospacer === SP2_RC)
const pw = pair2?.offtarget_pairwise
check('pairwise: computed only from same-chromosome pairs, sorted by distance',
  pw?.status === 'computed' && pw.n_pair_events === 2 &&
  pw.events[0].distance_bp === 850 && pw.events[1].distance_bp === 8300,
  JSON.stringify({ status: pw?.status, n: pw?.n_pair_events, ev: (pw?.events ?? []).map((e) => e.distance_bp) }))
check('pairwise: states that it is not risk summation',
  /不是.*相加/.test(String(pw?.note)), String(pw?.note).slice(0, 60))

// ── ④ paired_nickase：只保留异链且间距在窗口内 ────────────────────────────
const nick = op('evaluate_strategy', { ...CG, strategy: 'paired_nickase', max_offset_bp: 100, top_n: 1000 })
const nickPair = (nick.pairs ?? []).find((p) => p.left.protospacer === SP1 && p.right.protospacer === SP2_RC)
check('paired_nickase: opposite-strand pair kept with the nick offset reported',
  nickPair?.nickase_offset_bp === 40, JSON.stringify(nickPair && { off: nickPair.nickase_offset_bp }))
check('paired_nickase: every returned pair is cross-strand',
  (nick.pairs ?? []).every((p) => p.same_strand === false),
  JSON.stringify((nick.pairs ?? []).map((p) => p.same_strand)))
check('paired_nickase: offset window enforced (no pair beyond max_offset_bp)',
  (nick.pairs ?? []).every((p) => p.nickase_offset_bp <= 100))

// ── ⑤ 未实现策略：显式拒绝，不给假设计 ────────────────────────────────────
for (const s of ['prime_edit', 'hdr', 'multiplex_knockout']) {
  const r = op('evaluate_strategy', { ...CG, strategy: s })
  check(`unimplemented strategy "${s}" refuses honestly`,
    r.implemented === false && r.verdict === 'cannot_design' &&
    /未实现/.test(String(r.honesty)),
    JSON.stringify({ impl: r.implemented, verdict: r.verdict }))
}
const elsewhere = op('evaluate_strategy', { ...CG, strategy: 'base_edit' })
check('base_edit strategy points to the dedicated tool instead of faking geometry',
  elsewhere.implementation_state === 'elsewhere' && /graft_base_edit/.test(String(elsewhere.note)),
  JSON.stringify(elsewhere.implementation_state))

let singleCut = null
let singleCutError = ''
try {
  singleCut = op('evaluate_strategy', { candidates: [g1], strategy: 'single_cut' })
} catch (e) {
  singleCutError = e.message
}
check('single_cut accepts one candidate and delegates to the design tools',
  singleCut?.implemented === true &&
  singleCut?.verdict === 'use_design_tools' &&
  singleCut?.n_candidates === 1,
  singleCutError || JSON.stringify(singleCut))

// ── ⑥ 输入卫生 ────────────────────────────────────────────────────────────
let badStrategy = ''
try { op('evaluate_strategy', { ...CG, strategy: 'magic' }) } catch (e) { badStrategy = e.message }
check('unknown strategy fails loudly and lists the known ones',
  /unknown strategy/.test(badStrategy) && /deletion_pair/.test(badStrategy), badStrategy.slice(0, 140))

let tooFew = ''
try { op('evaluate_strategy', { candidates: [g1], strategy: 'deletion_pair' }) } catch (e) { tooFew = e.message }
check('fewer than two candidates fails loudly', /至少两条/.test(tooFew), tooFew.slice(0, 120))

summary('strategy')
