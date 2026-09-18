// test/offtarget-scan.mjs — Cas-OFFinder 真实扫描夹具（端到端，不是 mock）
//
// 夹具设计（全部可手算）：
//   filler1(100bp) + 'GGGGG' + guide(20) + 'AGG'          ← 精确匹配位点（0 mismatch）
//   + filler2(50bp) + guide_1mm(20) + 'AGG'               ← 1 mismatch 位点（错配在第 11 位）
//   + filler3(50bp)
// 断言：真实命中行的 chromosome/坐标/链/mismatch 数与错配位置，全部来自工具 stdout。
// 后端缺失时：GRAFT_STRICT=1 → FAIL；否则输出 SKIP-NOT-VALIDATED（不冒充已验证）。
import { check, summary, op, skip, pythonExe, PYDIR } from './harness.mjs'
import { spawnSync } from 'node:child_process'
import {
  copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// ---------- ⓪ 生产发现链：env → 自管目录 → PATH → sibling ----------
// 使用 Python 模块的临时副本验证发现逻辑；不在仓库 python/ 下放假二进制。
const discoveryRoot = mkdtempSync(join(tmpdir(), 'graft-offtarget-discovery-'))
copyFileSync(join(PYDIR, 'offtarget.py'), join(discoveryRoot, 'offtarget.py'))
copyFileSync(join(PYDIR, 'offtarget_interpret.py'), join(discoveryRoot, 'offtarget_interpret.py'))
const discoveryExe = join(discoveryRoot, 'discovered-cas-offinder.exe')
const siblingExe = join(discoveryRoot, 'cas-offinder.exe')
writeFileSync(discoveryExe, 'test-only discovery sentinel')

const discoveryScript = [
  'import json, os, sys',
  'sys.path.insert(0, ' + JSON.stringify(discoveryRoot.replace(/\\/g, '/')) + ')',
  'import offtarget',
  'offtarget.graft_bin_dir = ' +
    JSON.stringify(join(discoveryRoot, 'empty-bin').replace(/\\/g, '/')),
  'os.environ.pop("GRAFT_CAS_OFFINDER", None)',
  'mode = os.environ["GRAFT_DISCOVERY_MODE"]',
  'if mode == "env": os.environ["GRAFT_CAS_OFFINDER"] = os.environ["GRAFT_DISCOVERY_PATH"]',
  'elif mode == "path": offtarget.shutil.which = lambda _: os.environ["GRAFT_DISCOVERY_PATH"]',
  'else: offtarget.shutil.which = lambda _: None',
  'print(json.dumps(offtarget.locate_casoffinder()))',
].join('\n')

function discoveryProbe(mode) {
  const env = {
    ...process.env,
    GRAFT_DISCOVERY_MODE: mode,
    GRAFT_DISCOVERY_PATH: discoveryExe,
    PYTHONDONTWRITEBYTECODE: '1',
  }
  delete env.GRAFT_CAS_OFFINDER
  const res = spawnSync(pythonExe(), ['-I', '-c', discoveryScript], {
    cwd: discoveryRoot,
    env,
    encoding: 'utf8',
    windowsHide: true,
  })
  if (res.status !== 0) {
    return { ok: false, probe_error: res.stderr || res.error?.message || 'probe failed' }
  }
  try {
    return JSON.parse((res.stdout || '').trim())
  } catch {
    return { ok: false, probe_error: 'non-JSON: ' + (res.stdout || '').slice(-200) }
  }
}

const samePath = (a, b) =>
  String(a).replace(/\\/g, '/').toLowerCase() === String(b).replace(/\\/g, '/').toLowerCase()
const envProbe = discoveryProbe('env')
const pathProbe = discoveryProbe('path')
writeFileSync(siblingExe, 'test-only sibling sentinel')
const siblingProbe = discoveryProbe('sibling')
check('backend discovery honors GRAFT_CAS_OFFINDER first',
  envProbe.ok === true && envProbe.source === 'GRAFT_CAS_OFFINDER' &&
  samePath(envProbe.path, discoveryExe), JSON.stringify(envProbe))
check('backend discovery accepts cas-offinder from PATH',
  pathProbe.ok === true && pathProbe.source === 'PATH' &&
  samePath(pathProbe.path, discoveryExe), JSON.stringify(pathProbe))
check('backend discovery accepts a binary beside python/offtarget.py',
  siblingProbe.ok === true && siblingProbe.source === 'graft-python-dir' &&
  samePath(siblingProbe.path, siblingExe), JSON.stringify(siblingProbe))
rmSync(discoveryRoot, { recursive: true, force: true })

const BACKEND = op('offtarget_backend', {}).backend
const BIN = BACKEND?.path

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
const GUIDE_1MM = `${GUIDE.slice(0, 10)}A${GUIDE.slice(11)}`   // 第 11 位 G→A（seed 外）
const GUIDE_SEEDMM = `${GUIDE.slice(0, 19)}G${GUIDE.slice(20)}` // 第 20 位（seed 内：16..23）

const f1 = filler(100, 12345)
const f2 = filler(50, 67890)
const f3 = filler(50, 24680)
const f4 = filler(50, 13579)
const genomeSeq = `${f1}GGGGG${GUIDE}AGG${f2}${GUIDE_1MM}AGG${f3}${GUIDE_SEEDMM}AGG${f4}`

const exactPos0 = genomeSeq.indexOf(`${GUIDE}AGG`)
const nearPos0 = genomeSeq.indexOf(`${GUIDE_1MM}AGG`)
const seedPos0 = genomeSeq.indexOf(`${GUIDE_SEEDMM}AGG`)

if (!BACKEND?.ok || !BIN || !existsSync(BIN)) {
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

  // ---------- ②b 批次 C：结构化语义（search_completeness / assessment / per_guide）----------
  check('search_completeness enumerates what was NOT searched',
    res.search_completeness?.mismatch === 'searched' &&
    res.search_completeness?.dna_bulge === 'not_searched' &&
    res.search_completeness?.rna_bulge === 'not_searched' &&
    res.search_completeness?.structural_variation === 'not_searched' &&
    res.search_completeness?.sample_variants === 'not_searched',
    JSON.stringify(res.search_completeness))
  // 断言「API 里不存在 safety 结论字段」要按 **key** 走查：forbidden_phrasing 里出现 "safe"
  // 是设计的一部分（它正是禁词清单），字符串包含判断会误报。
  const hasKey = (obj, names) => {
    if (Array.isArray(obj)) return obj.some((x) => hasKey(x, names))
    if (obj && typeof obj === 'object') {
      return Object.keys(obj).some((k) => names.includes(k.toLowerCase()) || hasKey(obj[k], names))
    }
    return false
  }
  check('assessment refuses to conclude safety (no safe/risk_level key anywhere)',
    res.assessment?.safety_conclusion === 'not_supported' &&
    typeof res.assessment?.reason === 'string' &&
    !hasKey(res, ['safe', 'is_safe', 'safe_flag', 'risk_level', 'risk_class']),
    JSON.stringify(res.assessment))

  const pg = (res.per_guide ?? [])[0]
  check('per_guide aggregates hits for the query',
    pg && pg.query === `${GUIDE}AGG` && pg.n_hits === res.n_hits,
    JSON.stringify(pg && { q: pg.query, n: pg.n_hits }))
  check('per_guide reports the mismatch distribution',
    pg && pg.hits_by_mismatch && pg.hits_by_mismatch['0'] === 1 && pg.hits_by_mismatch['1'] === 2,
    JSON.stringify(pg?.hits_by_mismatch))
  check('per_guide flags hits whose mismatch falls inside the PAM-proximal seed',
    pg && pg.seed_region_hits === 1,
    `seed_region_hits=${pg?.seed_region_hits} (seed window = last 8 of the 23-mer)`)
  check('per_guide reports the nearest site with its coordinates',
    pg && pg.nearest_site && pg.nearest_site.mismatches === 0 &&
    pg.nearest_site.position_1based === exactPos0 + 1,
    JSON.stringify(pg?.nearest_site))
  check('seed-mutant site is found at the expected coordinate',
    (res.hits ?? []).some((h) => h.position_0based === seedPos0 && h.mismatches === 1),
    `expected ${seedPos0}`)

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
