// test/offtarget-scan.mjs — Cas-OFFinder 真实扫描夹具（端到端，不是 mock）
//
// 夹具设计（全部可手算）：
//   filler1(100bp) + 'GGGGG' + guide(20) + 'AGG'          ← 精确匹配位点（0 mismatch）
//   + filler2(50bp) + guide_1mm(20) + 'AGG'               ← 1 mismatch 位点（错配在第 11 位）
//   + filler3(50bp)
// 断言：真实命中行的 chromosome/坐标/链/mismatch 数与错配位置，全部来自工具 stdout。
// 后端缺失时：GRAFT_STRICT=1 → FAIL；否则 skip（不许静默跳过）。
import { check, summary, op, skip } from './harness.mjs'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

const BIN = join(homedir(), '.dsh', 'dsh-bio-graft', 'bin', 'cas-offinder.exe')

function filler(n, seed) {
  let s = ''
  let x = seed
  for (let i = 0; i < n; i += 1) {
    x = (x * 1103515245 + 12345) & 0x7fffffff
    s += 'ACGT'[x % 4]
  }
  return s
}

const GUIDE = 'ACGTACGTACGTACGTACGT'
const GUIDE_1MM = `${GUIDE.slice(0, 10)}A${GUIDE.slice(11)}`   // 第 11 位 G→A

const f1 = filler(100, 12345)
const f2 = filler(50, 67890)
const f3 = filler(50, 24680)
const genomeSeq = `${f1}GGGGG${GUIDE}AGG${f2}${GUIDE_1MM}AGG${f3}`

const exactPos0 = genomeSeq.indexOf(`${GUIDE}AGG`)
const nearPos0 = genomeSeq.indexOf(`${GUIDE_1MM}AGG`)

if (!existsSync(BIN)) {
  skip('cas-offinder scan fixtures', `backend not installed at ${BIN}`)
} else {
  const dir = join(tmpdir(), `graft-offtarget-${process.pid}`)
  mkdirSync(dir, { recursive: true })
  const genome = join(dir, 'fixture_genome.fa')
  writeFileSync(genome, `>chrTest\n${genomeSeq}\n`, { encoding: 'utf8' })
  const genomeNative = genome.replace(/\\/g, '/')

  // ---------- ① preflight ----------
  const pre = op('offtarget_scan', { genome_file: genomeNative, preflight_only: true })
  check('preflight reports FASTA records without scanning',
    pre.mode === 'preflight' && pre.genome_check?.n_records === 1,
    JSON.stringify(pre.genome_check?.n_records))

  // ---------- ② 真实扫描 ----------
  const res = op('offtarget_scan', {
    genome_file: genomeNative,
    queries: [`${GUIDE}AGG`],
    pattern: 'N20NGG',
    mismatches: 3,
    device: 'auto',
    top_n: 50,
  }, { timeoutMs: 300_000 })

  check('scan echoes backend path', typeof res.backend?.path === 'string')
  check('scan echoes search parameters (mismatches/pattern/n_queries)',
    res.search_parameters?.mismatches === 3 &&
    res.search_parameters?.pattern === `NNNNNNNNNNNNNNNNNNNNNGG` &&
    res.search_parameters?.n_queries === 1,
    JSON.stringify(res.search_parameters))
  check('scan auto-selected a working device and reports the note',
    typeof res.search_parameters?.device === 'string' &&
    typeof res.search_parameters?.device_note === 'string',
    `${res.search_parameters?.device}`)
  check('scan writes a raw hits file',
    typeof res.raw_hits_file === 'string' && existsSync(res.raw_hits_file))

  const exact = (res.hits ?? []).find(
    (h) => h.chromosome === 'chrTest' && h.position_0based === exactPos0 && h.mismatches === 0)
  check('exact-match hit found at the expected 0-based coordinate',
    Boolean(exact), `expected ${exactPos0}; got ${JSON.stringify((res.hits ?? []).slice(0, 3))}`)
  if (exact) {
    check('hit rows carry strand and 1-based echo',
      exact.strand === '+' && exact.position_1based === exactPos0 + 1,
      `${exact.strand}/${exact.position_1based}`)
    check('hit carries the matched sequence verbatim',
      exact.matched_sequence === `${GUIDE}AGG`, exact.matched_sequence)
  }

  const near = (res.hits ?? []).find(
    (h) => h.chromosome === 'chrTest' && h.position_0based === nearPos0 && h.mismatches === 1)
  check('1-mismatch near-match found at the expected coordinate',
    Boolean(near), `expected ${nearPos0}`)
  if (near) {
    check('mismatch position is reported 1-based (index 11)',
      JSON.stringify(near.mismatch_positions_1based) === '[11]',
      JSON.stringify(near.mismatch_positions_1based))
  }

  check('scan output carries the machine-readable boundary statement',
    typeof res.interpretation_boundary === 'string' &&
    res.interpretation_boundary.includes('不构成'),
    String(res.interpretation_boundary).slice(0, 60))

  // ---------- ③ 假阴性护栏：0 命中必须带排查提示 ----------
  const empty = op('offtarget_scan', {
    genome_file: genomeNative,
    queries: [`${filler(23, 999).slice(0, 23)}`],
    pattern: 'N20NGG',
    mismatches: 0,
    device: 'auto',
    top_n: 10,
  }, { timeoutMs: 300_000 })
  check('zero hits returns a loud troubleshooting warning (not "safe")',
    empty.n_hits === 0 && typeof empty.zero_hit_warning === 'string' &&
    empty.zero_hit_warning.includes('待排查'),
    `n_hits=${empty.n_hits}`)

  // ---------- ④ 输入错误必须响亮失败（长度不等 / 非法字符）----------
  let lenMismatchThrew = false
  try {
    op('offtarget_scan', { genome_file: genomeNative, queries: ['ACGTAGG'], pattern: 'N20NGG' })
  } catch (e) {
    lenMismatchThrew = /长度/.test(e.message) || /length/i.test(e.message)
  }
  check('query/pattern length mismatch fails loudly', lenMismatchThrew)

  // ---------- ⑤ 基因组不存在时的引导 ----------
  const missing = op('offtarget_scan', {
    genome_file: join(dir, 'nope.fa').replace(/\\/g, '/'),
    queries: [`${GUIDE}AGG`], pattern: 'N20NGG',
  })
  check('missing genome returns preflight failure with hint',
    missing.ok === false && missing.genome_check?.exists === false &&
    typeof missing.hint === 'string',
    JSON.stringify(missing.error))
}

summary('offtarget-scan')
