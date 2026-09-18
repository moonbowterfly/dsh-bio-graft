// test/rank.mjs — graft_rank 声明式排名的黄金夹具（人工可算，期望值全部写死）。
//
// 设计契约（GPT 裁决 #3 + #13）：
//   · 三种 operator：hard_filters（约束）/ lexicographic（字典序）/ pareto（支配）/ weighted（仅显式给权重时）
//   · 秩是 policy-dependent：返回体必须带 policy_id + policy_digest + policy_echo
//   · **禁止默认隐形权重**；weighted 必须带 disclaimer，且给的是 declared_objective_value（非 "score"）
//   · 负证据语义：过滤器依赖的数据缺失时必须**排除并说明 not_searched/missing**，绝不静默通过
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { check, summary, op, REPO } from './harness.mjs'

const RANK_CONTRACT = JSON.parse(readFileSync(join(REPO, 'rank-contract.json'), 'utf8'))
const [GC_CONTENT_MIN, GC_CONTENT_MAX] = RANK_CONTRACT.canonicalGcFilters

// 夹具：4 条候选（字段取自 graft_design + graft_score 的真实形态）
const cand = (spacer, hits, gc, pal, offtotal) => ({
  protospacer: spacer,
  pam: 'AGG',
  start_0: 10,
  end_0: 33,
  strand: '+',
  template_hits: hits,
  on_target_scores: { gc_content: gc, max_self_palindrome: pal, homopolymer_runs: [], gc_class: 'mid' },
  ...(offtotal === undefined ? {} : {
    offtarget_summary: { hits_by_mismatch: { 0: 1, 1: 0, 2: 0, 3: offtotal - 1 }, total: offtotal },
  }),
})
const A = cand('A'.repeat(20), 1, 0.50, 6, 3)
const B = cand('B'.repeat(20), 1, 0.40, 6, 1)
const C = cand('C'.repeat(20), 2, 0.50, 14, 0)   // 多位点 → 硬过滤应剔除
const D = cand('D'.repeat(20), 1, 0.50, 14, 2)
const CANDIDATES = [A, B, C, D]

// ---------- ① 字典序（含硬过滤）----------
const lex = op('rank_candidates', {
  candidates: CANDIDATES,
  policy: 'lexicographic',
  order: ['template_hits:min', 'max_self_palindrome:min', 'gc_abs_dev:min'],
  hard_filters: { template_hits_max: 1 },
})
check('lexicographic: excluded candidates carry reasons',
  lex.n_excluded === 1 && lex.excluded[0].protospacer === C.protospacer &&
  lex.excluded[0].reasons.some((r) => r.includes('template_hits')),
  JSON.stringify(lex.excluded))
check('lexicographic: rank order A → B → D',
  lex.ranked.map((r) => r.protospacer).join(',') ===
  [A, B, D].map((c) => c.protospacer).join(','),
  lex.ranked.map((r) => `#${r.rank}${r.protospacer[0]}`).join(' '))
check('lexicographic: policy_id + policy_digest present',
  typeof lex.policy_id === 'string' && /^sha256:[0-9a-f]{16,}$/.test(lex.policy_digest ?? ''),
  `${lex.policy_id} / ${lex.policy_digest}`)
check('lexicographic: vector values travel with the rank',
  lex.ranked[0].vector_values.template_hits === 1 &&
  lex.ranked[0].vector_values.max_self_palindrome === 6 &&
  lex.ranked[0].vector_values.gc_abs_dev === 0,
  JSON.stringify(lex.ranked[0].vector_values))
check('lexicographic: no opaque score field anywhere',
  !JSON.stringify(lex).includes('"score"'))
check('lexicographic: no opaque quality_score field anywhere',
  !JSON.stringify(lex).includes('quality_score'))

// ---------- ② Pareto ----------
const pareto = op('rank_candidates', {
  candidates: CANDIDATES,
  policy: 'pareto',
  objectives: ['template_hits:min', 'max_self_palindrome:min', 'gc_abs_dev:min'],
  hard_filters: { template_hits_max: 1 },
})
check('pareto: front contains exactly A (B and D are dominated)',
  pareto.pareto_front.length === 1 && pareto.pareto_front[0] === A.protospacer,
  JSON.stringify(pareto.pareto_front))
check('pareto: dominated candidates list who dominates them',
  pareto.ranked.find((r) => r.protospacer === B.protospacer)?.dominated_by?.includes(A.protospacer) &&
  pareto.ranked.find((r) => r.protospacer === D.protospacer)?.dominated_by?.includes(A.protospacer),
  JSON.stringify(pareto.ranked.map((r) => ({ p: r.protospacer[0], d: r.dominated_by?.length }))))
check('pareto: pareto_rank is 1 for the front, >1 otherwise',
  pareto.ranked.find((r) => r.protospacer === A.protospacer).pareto_rank === 1 &&
  (pareto.ranked.find((r) => r.protospacer === B.protospacer).pareto_rank ?? 1) > 1)

// ---------- ③ weighted（仅在显式给权重时）----------
const weighted = op('rank_candidates', {
  candidates: CANDIDATES,
  policy: 'weighted',
  weights: { gc_abs_dev: 1, max_self_palindrome: 0.1 },
  hard_filters: { template_hits_max: 1 },
})
check('weighted: declared_objective_value is the transparent weighted sum (raw units)',
  weighted.ranked[0].declared_objective_value === 0.6 &&
  weighted.ranked[1].declared_objective_value === 0.7 &&
  weighted.ranked[2].declared_objective_value === 1.4,
  JSON.stringify(weighted.ranked.map((r) => r.declared_objective_value)))
check('weighted: disclaimer present and forbids report-grade use',
  typeof weighted.disclaimer === 'string' && weighted.disclaimer.includes('不得'),
  String(weighted.disclaimer).slice(0, 80))
check('weighted: weights are echoed in the policy payload',
  JSON.stringify(weighted.policy.weights) === JSON.stringify({ gc_abs_dev: 1, max_self_palindrome: 0.1 }))

// ---------- ③b 排名目标缺失必须 fail-closed ----------
const MISSING = { protospacer: 'M'.repeat(20), template_hits: 0 }
const COMPLETE = cand('N'.repeat(20), 1, 0.50, 10, 1)
const weightedMissing = op('rank_candidates', {
  candidates: [MISSING, COMPLETE],
  policy: 'weighted',
  weights: { gc_abs_dev: 1, max_self_palindrome: 1 },
})
check('weighted: missing objective metrics are excluded instead of receiving zero cost',
  weightedMissing.n_ranked === 1 &&
  weightedMissing.ranked[0]?.protospacer === COMPLETE.protospacer &&
  weightedMissing.excluded.some((e) => e.protospacer === MISSING.protospacer &&
    e.reasons.some((r) => /not_searched|missing/i.test(r))),
  JSON.stringify(weightedMissing))

const paretoMissing = op('rank_candidates', {
  candidates: [MISSING, COMPLETE],
  policy: 'pareto',
  objectives: ['template_hits:min', 'max_self_palindrome:min', 'gc_abs_dev:min'],
})
check('pareto: candidates missing any objective axis are excluded and cannot dominate',
  paretoMissing.n_ranked === 1 &&
  paretoMissing.pareto_front.length === 1 &&
  paretoMissing.pareto_front[0] === COMPLETE.protospacer &&
  paretoMissing.excluded.some((e) => e.protospacer === MISSING.protospacer),
  JSON.stringify(paretoMissing))

// ---------- ④ 负证据语义：依赖缺失的数据不得静默通过 ----------
// 造两条**从未做过脱靶分析**的候选（无 offtarget_summary 字段）
const E1 = cand('E'.repeat(20), 1, 0.50, 6)
const E2 = cand('F'.repeat(20), 1, 0.45, 6)
const noData = op('rank_candidates', {
  candidates: [E1, E2],
  policy: 'lexicographic',
  order: ['template_hits:min'],
  hard_filters: { offtarget_total_max: 5 },
})
check('hard filter over missing data excludes with a NOT_SEARCHED reason (never silent pass)',
  noData.ranked.length === 0 && noData.n_excluded === 2 &&
  noData.excluded.every((e) => e.reasons.some((r) => /not_searched|missing/i.test(r))),
  JSON.stringify(noData.excluded))

// ---------- ⑤ 输入卫生 ----------
let badPolicy = false
try {
  op('rank_candidates', { candidates: CANDIDATES, policy: 'magic' })
} catch (e) {
  badPolicy = /policy/i.test(e.message)
}
check('unknown policy fails loudly', badPolicy)

let noWeights = false
try {
  op('rank_candidates', { candidates: CANDIDATES, policy: 'weighted' })
} catch (e) {
  noWeights = /weights/i.test(e.message)
}
check('weighted without explicit weights fails loudly (no implicit weights)', noWeights)

// ---------- ⑥ 脱靶摘要的两种形态都要认（真实会话：agent 手工合并时产出扁平形态）----------
const flat = {
  protospacer: 'G'.repeat(20), pam: 'TGG', start_0: 1, end_0: 24, strand: '+',
  template_hits: 1,
  on_target_scores: { gc_content: 0.5, max_self_palindrome: 4, homopolymer_runs: [] },
  offtarget_summary: { offtarget_total: 2, offtarget_mm0: 1, offtarget_mm1: 1, offtarget_mm2: 0, offtarget_mm3: 0 },
}
const flatRanked = op('rank_candidates', {
  candidates: [flat],
  policy: 'lexicographic',
  order: ['offtarget_mm0:min'],
  hard_filters: { offtarget_total_max: 5, offtarget_mm0_max: 1 },
})
check('flat offtarget_summary shape is understood (not treated as not_searched)',
  flatRanked.n_ranked === 1 &&
  flatRanked.ranked[0].vector_values.offtarget_mm0 === 1,
  JSON.stringify({ n: flatRanked.n_ranked, excl: flatRanked.excluded }))

// ---------- ⑦ homopolymer 的三层回退：nested → flat runs → flat max ----------
const flatHomoTooLong = {
  protospacer: 'H'.repeat(20), template_hits: 1, gc_content: 0.5,
  max_self_palindrome: 4, homopolymer_max: 5,
}
const flatHomoFiltered = op('rank_candidates', {
  candidates: [flatHomoTooLong],
  policy: 'lexicographic',
  order: ['homopolymer_max:min'],
  hard_filters: { homopolymer_max_max: 4 },
})
check('flat homopolymer_max participates in hard filters',
  flatHomoFiltered.n_ranked === 0 && flatHomoFiltered.n_excluded === 1 &&
  flatHomoFiltered.excluded[0].reasons.some((r) => /homopolymer_max=5/.test(r)),
  JSON.stringify(flatHomoFiltered))

const flatRuns = {
  protospacer: 'I'.repeat(20), template_hits: 1, gc_content: 0.5,
  max_self_palindrome: 4, homopolymer_runs: ['AAAAA'],
}
const flatMax = {
  protospacer: 'J'.repeat(20), template_hits: 1, gc_content: 0.5,
  max_self_palindrome: 4, homopolymer_max: 3,
}
const flatHomoSorted = op('rank_candidates', {
  candidates: [flatRuns, flatMax],
  policy: 'lexicographic',
  order: ['homopolymer_max:min'],
})
check('flat homopolymer runs/max participate in sorting with the declared precedence',
  flatHomoSorted.ranked.map((x) => x.protospacer).join(',') ===
    [flatMax.protospacer, flatRuns.protospacer].join(',') &&
  flatHomoSorted.ranked[0].vector_values.homopolymer_max === 3 &&
  flatHomoSorted.ranked[1].vector_values.homopolymer_max === 5,
  JSON.stringify(flatHomoSorted.ranked))

// ---------- ⑧ GC filter 契约由 rank-contract.json 定义 ----------
const canonicalGc = op('rank_candidates', {
  candidates: [A],
  policy: 'lexicographic',
  order: ['template_hits:min'],
  hard_filters: { [GC_CONTENT_MIN]: 0.3, [GC_CONTENT_MAX]: 0.7 },
})
check('canonical gc_content_min/max filters are accepted',
  canonicalGc.n_ranked === 1 && canonicalGc.n_excluded === 0,
  JSON.stringify(canonicalGc))

// 旧别名必须响亮失败，并列出契约中的规范名。
let errText = ''
try {
  op('rank_candidates', { candidates: [A], policy: 'lexicographic', order: ['template_hits:min'], hard_filters: { gc_min: 0.3 } })
} catch (e) { errText = e.message }
check('unknown filter name lists the valid names',
  /gc_min/.test(errText) && errText.includes(GC_CONTENT_MIN) &&
  errText.includes(GC_CONTENT_MAX) && /可用/.test(errText),
  errText.slice(0, 160))

summary('rank')
