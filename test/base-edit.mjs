// test/base-edit.mjs — 碱基编辑设计（graft_base_edit）黄金夹具（全部手工可算）。
//
// 契约（GPT 裁决 #5/#9）：
//   · 五层 profile（targeting/chemistry/activity/evidence/applicability）原样带出，可逐层引用
//   · **窗口内 = 几何兼容，不推活性**：payload 里不得出现任何效率/活性预测字段
//   · 链语义三件套：guide_strand / edited_physical_strand / reference_reported_substitution
//     （反链 guide 的 C→T 在参考正链上是 **G→A**）
//   · bystander 必须显式列出；密码子后果缺 CDS 声明时 not_applicable，绝不猜读码框
import { check, summary, op } from './harness.mjs'

// ── 夹具构造（每一步都写出来，便于复核）────────────────────────────────────
// PRE(11) + SPACER(20) + PAM(TGG) + POST(11)
// SPACER = 'GACT' + 'CAG' + 'TACGTACGTACCG'
//   位置：1 G 2 A 3 C 4 T 5 **C** 6 A 7 G 8 T …（窗口 4–8 内只有位置 5 是 C）
// CDS 从 0 开始、frame 0：位置 15 是密码子起点 → codon = SEQ[15:18] = 'CAG'(Gln)
//   → 位置 5 的 C→T 把它变成 'TAG' = 终止密码子（nonsense）
const PRE = 'TTTTAAAACCC'
const SPACER = 'GACTCAGTACGTACGTACCG'
const PAM = 'TGG'
const POST = 'AAACCCAAACC'
const SEQ = PRE + SPACER + PAM + POST
// 期望：protospacer 位置 5 的 C 落在序列 0-based 15
const EXPECT_POS_0 = 15

const revcomp = (s) => s.split('').reverse().map((c) => ({ A: 'T', C: 'G', G: 'C', T: 'A', N: 'N' }[c])).join('')
const SEQ_MINUS = revcomp(SEQ)   // 同一位点在反链 guide 场景

// ── ① 五层 profile 注册表 ──────────────────────────────────────────────────
const profiles = op('profile_list', {})
const be = (profiles.base_editors ?? []).find((p) => p.name === 'BE3')
const abe = (profiles.base_editors ?? []).find((p) => p.name === 'ABE7.10')
check('base editor registry exposes the five layers',
  Boolean(be?.targeting && be?.chemistry && be?.activity && be?.evidence && be?.applicability),
  JSON.stringify(be && Object.keys(be)))
check('BE3 core window is 4–8 with the PAM-as-21–23 counting convention',
  JSON.stringify(be?.activity?.core_window) === '[4,8]' &&
  /21–23|21-23/.test(String(be?.activity?.window_counting)),
  JSON.stringify(be?.activity))
check('ABE7.10 core window is 4–7 (primary-literature value)',
  JSON.stringify(abe?.activity?.core_window) === '[4,7]', JSON.stringify(abe?.activity?.core_window))
check('each profile carries evidence + verified flag',
  be?.evidence?.verified === true && /Komor|Gaudelli|literature|window/i.test(String(be?.evidence?.window_evidence)),
  JSON.stringify(be?.evidence).slice(0, 200))
check('applicability declares that NO efficiency model is bundled',
  be?.applicability?.efficiency_model_available === false &&
  /不推.*高效|未内置/.test(String(be?.applicability?.extrapolation_warning)),
  String(be?.applicability?.extrapolation_warning).slice(0, 80))

// ── ② CBE（+ 链）：单碱基、C→T、密码子后果 nonsense ────────────────────────
const cbe = op('base_edit_design', { sequence: SEQ, editor: 'BE3', cds_start_0: 0, top_n: 50 })
const myPlus = (cbe.candidates ?? []).find((c) => c.protospacer === SPACER && c.guide_strand === '+')
check('CBE: the designed guide is found on the + strand', Boolean(myPlus))
if (myPlus) {
  const e = myPlus.editable_positions[0]
  check('CBE: exactly one editable C in the core window (positions 4–8)',
    myPlus.n_editable_in_window === 1 && myPlus.clean_single_edit === true &&
    e.protospacer_pos_1based === 5,
    JSON.stringify(myPlus.editable_positions.map((x) => x.protospacer_pos_1based)))
  check('CBE: genome coordinate is independently verifiable (SEQ[pos] === "C")',
    e.genome_pos_0based === EXPECT_POS_0 && SEQ[e.genome_pos_0based] === 'C',
    `pos=${e.genome_pos_0based} base=${SEQ[e.genome_pos_0based]}`)
  check('CBE: reference-reported substitution is C→T on the + strand',
    e.reference_reported_substitution.from === 'C' && e.reference_reported_substitution.to === 'T',
    JSON.stringify(e.reference_reported_substitution))
  check('CBE: codon effect is nonsense CAG→TAG (Gln→stop)',
    e.codon_effect?.consequence === 'nonsense' && e.codon_effect?.ref_codon === 'CAG' &&
    e.codon_effect?.alt_codon === 'TAG' && e.codon_effect?.aa_alt === '*',
    JSON.stringify(e.codon_effect))
  check('CBE: nonsense carries an explicit warning (target vs risk depends on intent)',
    myPlus.warnings.some((w) => w.includes('终止密码子')),
    JSON.stringify(myPlus.warnings))
}
check('payload states geometry-vs-efficiency separation',
  /几何兼容/.test(String(cbe.geometry_vs_efficiency)) &&
  /不预测/.test(String(cbe.geometry_vs_efficiency)))
check('payload contains no activity/efficiency prediction field',
  !JSON.stringify(cbe).match(/"efficiency(_score)?"|"activity_score"|"predicted_activity"/),
  JSON.stringify(Object.keys(cbe)))

// ── ③ 反链语义：同一物理位点，C→T 在参考正链上是 G→A ──────────────────────
const cbeMinus = op('base_edit_design', { sequence: SEQ_MINUS, editor: 'BE3', top_n: 50 })
const myMinus = (cbeMinus.candidates ?? []).find((c) => c.protospacer === SPACER)
check('minus-strand guide found for the mirrored construct',
  Boolean(myMinus) && myMinus?.guide_strand === '-', JSON.stringify(myMinus?.guide_strand))
if (myMinus) {
  const e = myMinus.editable_positions[0]
  check('minus strand: edited_physical_strand is reported as "-"',
    e.edited_physical_strand === '-')
  check('minus strand: reference-reported substitution flips to G→A',
    e.reference_reported_substitution.from === 'G' && e.reference_reported_substitution.to === 'A',
    JSON.stringify(e.reference_reported_substitution))
  check('minus strand: reported coordinate really points at a G in the reference (+ strand)',
    SEQ_MINUS[e.genome_pos_0based] === 'G',
    `pos=${e.genome_pos_0based} base=${SEQ_MINUS[e.genome_pos_0based]}`)
}

// ③a strand 参数必须决定实际候选集合；both 是 + 与 - 的并集上界。
const cbePlusOnly = op('base_edit_design', {
  sequence: SEQ_MINUS, editor: 'BE3', strand: '+', top_n: 50,
})
const cbeMinusOnly = op('base_edit_design', {
  sequence: SEQ_MINUS, editor: 'BE3', strand: '-', top_n: 50,
})
const candidateKey = (c) =>
  [c.protospacer, c.pam, c.start_0, c.end_0, c.guide_strand].join('|')
const bothKeys = new Set((cbeMinus.candidates ?? []).map(candidateKey))
const unionKeys = new Set([
  ...(cbePlusOnly.candidates ?? []).map(candidateKey),
  ...(cbeMinusOnly.candidates ?? []).map(candidateKey),
])
check('strand="+": returns only plus-strand candidates',
  (cbePlusOnly.candidates ?? []).every((c) => c.guide_strand === '+'),
  JSON.stringify(cbePlusOnly.candidates?.map((c) => c.guide_strand)))
check('strand="-": actually scans the reverse strand and is non-empty',
  (cbeMinusOnly.candidates ?? []).length > 0 &&
  (cbeMinusOnly.candidates ?? []).every((c) => c.guide_strand === '-'),
  JSON.stringify({ scanned: cbeMinusOnly.n_candidates_scanned,
    returned: cbeMinusOnly.n_returned,
    strands: cbeMinusOnly.candidates?.map((c) => c.guide_strand) }))
check('strand="both": candidate set contains the union of + and -',
  [...unionKeys].every((key) => bothKeys.has(key)),
  JSON.stringify({ both: [...bothKeys], union: [...unionKeys] }))

// ③b 反链候选 + 声明的 + 链 CDS：密码子后果必须用**参考正链碱基**算
const cbeMinusCds = op('base_edit_design', {
  sequence: SEQ_MINUS, editor: 'BE3', cds_start_0: 0, cds_strand: '+', top_n: 50,
})
const myMinusCds = (cbeMinusCds.candidates ?? []).find((c) => c.protospacer === SPACER)
const emc = myMinusCds?.editable_positions?.[0]
check('minus strand + declared + strand CDS → codon effect IS computed',
  emc?.codon_effect?.status === 'computed', JSON.stringify(emc?.codon_effect))
check('minus strand codon effect uses the reference + strand base (G), not the protospacer base',
  (() => {
    const ce = emc?.codon_effect
    if (!ce || ce.status !== 'computed') return false
    const offset = emc.genome_pos_0based - 0
    return ce.ref_codon[offset % 3] === 'G' && ce.alt_codon[offset % 3] === 'A'
  })(),
  JSON.stringify(emc?.codon_effect))

// ③c CDS 声明在 − 链 → 本版本显式 not_applicable（不推断）
const minusCds = op('base_edit_design', {
  sequence: SEQ, editor: 'BE3', cds_start_0: 0, cds_strand: '-', top_n: 5,
})
const mcd = minusCds.candidates?.[0]?.editable_positions?.[0]
check('cds_strand="-" is explicitly not_applicable (no inference)',
  mcd?.codon_effect?.status === 'not_applicable' && /cds_strand/.test(String(mcd?.codon_effect?.reason)),
  JSON.stringify(mcd?.codon_effect))

// ── ④ bystander：窗口内两个 C 必须显式列出并给警告 ────────────────────────
const SPACER_B = 'GACTCACTACGTACGTACCG'   // 位置 5 与 7 都是 C
const SEQ_B = PRE + SPACER_B + PAM + POST
const cbeB = op('base_edit_design', { sequence: SEQ_B, editor: 'BE3', cds_start_0: 0, top_n: 50 })
const myB = (cbeB.candidates ?? []).find((c) => c.protospacer === SPACER_B)
check('bystander: two editable C in the window are both reported',
  myB?.n_editable_in_window === 2 && myB?.clean_single_edit === false,
  JSON.stringify(myB?.editable_positions?.map((x) => x.protospacer_pos_1based)))
check('bystander: warning forbids claiming a clean C→T',
  myB?.warnings?.some((w) => w.includes('bystander')), JSON.stringify(myB?.warnings))
check('bystander: position 3 (outside the core window) is NOT editable',
  !myB?.editable_positions?.some((x) => x.protospacer_pos_1based === 3))

// ── ⑤ ABE：A→G，窗口 4–7（位置 3 的 A 不算）────────────────────────────────
const SPACER_ABE = 'GACT' + 'CAG' + 'TACGTACGTACCG'   // 窗口 4–7 内的 A 位于位置 6
const SEQ_ABE = PRE + SPACER_ABE + PAM + POST
const abeRes = op('base_edit_design', { sequence: SEQ_ABE, editor: 'ABE7.10', top_n: 50 })
const myA = (abeRes.candidates ?? []).find((c) => c.protospacer === SPACER_ABE)
check('ABE: finds the A at protospacer position 6 and reports A→G',
  myA?.editable_positions?.[0]?.protospacer_pos_1based === 6 &&
  myA?.editable_positions?.[0]?.reference_reported_substitution.from === 'A' &&
  myA?.editable_positions?.[0]?.reference_reported_substitution.to === 'G',
  JSON.stringify(myA?.editable_positions))
check('ABE: window ends at 7 (an A at position 8 would be excluded)',
  JSON.stringify(abeRes.window_used).includes('7'), JSON.stringify(abeRes.window_used))

// ── ⑥ 未声明 CDS → not_applicable（不猜读码框）────────────────────────────
const noCds = op('base_edit_design', { sequence: SEQ, editor: 'BE3', top_n: 5 })
const first = noCds.candidates?.[0]?.editable_positions?.[0]
check('without cds_start_0 the codon effect is explicitly not_applicable',
  first?.codon_effect?.status === 'not_applicable' &&
  /未声明 cds_start_0/.test(String(first?.codon_effect?.reason)),
  JSON.stringify(first?.codon_effect))

// ── ⑦ 未知编辑器响亮失败 ──────────────────────────────────────────────────
let unknownErr = ''
try {
  op('base_edit_design', { sequence: SEQ, editor: 'BE9-magic' })
} catch (e) { unknownErr = e.message }
check('unknown base editor fails loudly and lists what is available',
  /unknown base editor/.test(unknownErr) && /BE3/.test(unknownErr), unknownErr.slice(0, 160))

summary('base-edit')
