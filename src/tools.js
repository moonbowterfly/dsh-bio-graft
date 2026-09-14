// dsh-bio-graft — 工具层（生命周期 TARGET→DESIGN→RANK→VERIFY→AUDIT）
// 全部执行走 python/graft_ops.py（JSON stdin 协议）；Cas-OFFinder 由 offtarget.py
// 调外部 BSD-3 二进制（graft 不 bundle）。
//
// op 一览：
//   graft_profiles        — 列出内置 NucleaseProfile（编辑酶注册表，含证据分级）
//   graft_design          — sgRNA 枚举 + 评分向量 + 切割位点（不打综合分）
//   graft_score           — 对已有候选补打评分向量
//   graft_offtarget       — Cas-OFFinder 脱靶扫描（可先 preflight 体检基因组）
//   graft_backend_status  — 后端探测 / 设备列表 / ensure 自动安装
//   graft_plan_save       — EditPlan 保存/追加 run（append-only 账本）
//   graft_plan_load       — EditPlan 读回（plan + 全部 runs 时间线）
import { defineTool } from '@deepseek-ai/dsh-tools'
import { callGraft } from './python.js'

/** graft_ops 通用工具工厂（graft op 全部直接透传 JSON）。
 *
 * ⚠️ 传了自定义 `execute` 的工具必须走自己的实现——2026-09-14 真实会话实测：
 * 工厂无条件覆盖 execute 会让分支型工具（graft_backend_status 的 status/devices/ensure）
 * 永远落到 callGraft(undefined) → "unknown op: None"，而 agent 会把它当成工具故障去自愈。
 */
function graftTool(opts) {
  return defineTool({
    name: opts.name,
    description: opts.description,
    parameters: opts.parameters,
    timeoutMs: opts.timeoutMs ?? 120_000,
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }],
    },
    async execute(args) {
      if (typeof opts.execute === 'function') return opts.execute(args)
      return callGraft(opts.op, args, { timeoutMs: opts.timeoutMs ?? 120_000 })
    },
  })
}

export function registerTools(ctx) {
  const disposers = []

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_profiles',
    description:
      '列出内置编辑酶/NucleaseProfile（graft 的语义基石，所有下游都从 profile 读）。' +
      '每个 profile 返回：PAM 模式（IUPAC，如 NGG/TTTV）、PAM 位置（3prime/5prime）、' +
      'spacer 长度、切点偏移与结构（blunt/staggered）、评分文献引用，以及 **verified / pam_source ' +
      '证据分级**——verified=false 表示该 PAM/几何尚未对一手文献核对，报告里必须如实转述，' +
      '不得当作既定事实。选编辑器/查 PAM 之前先跑本工具。' +
      '触发词：编辑酶、Cas9、Cas12、有哪些编辑器、PAM 规则、spacer 长度、切割位点。',
    parameters: {},
    op: 'profile_list',
    timeoutMs: 60_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_design',
    description:
      'sgRNA 候选枚举 + on-target **评分向量** + 切割位点。输入目标序列（FASTA 或裸 DNA，支持多行/多条 FASTA）' +
      '与编辑酶名，按 NucleaseProfile 的 PAM 语法（IUPAC 感知）双向扫描，返回 GuideCandidate 列表：' +
      'protospacer / pam / strand / start_0,end_0（0-based 半开区间，**含 PAM**）/ start_1,end_1 / ' +
      '**cut_site_0（切割位点，附 cut_site_convention 口径与 cut_site_verified）** / template_hits（模板内出现次数）。' +
      '**不打综合分**：rank 必须由 graft_rank/graft_plan_save 按声明的 objective 完成；' +
      '「87.3 分」是伪精确，禁止只向用户报一个分数。' +
      '敲除类实验必须剔除 template_hits>1 的候选（多位点切割）。' +
      '触发词：设计 sgRNA、找 guide、候选 sgRNA、编辑位点设计、crispr 设计、切割位点、敲除设计。',
    parameters: {
      sequence: { type: 'string', required: true, description: '目标序列（FASTA 或裸 DNA；多行/多条 FASTA 均支持）' },
      editor: { type: 'string', description: '编辑酶名，如 SpCas9/Cas12a/SpG（默认 SpCas9；先用 graft_profiles 查）' },
      top_n: { type: 'number', description: '返回候选数上限（默认 100；n_candidates_raw 始终是截断前的真实数量）' },
      scan_both_strands: { type: 'boolean', description: '是否双链扫描（默认 true；false 只扫正链）' },
      record: { type: 'number', description: '多条 FASTA 时取第几条（0-based，默认 0）' },
      position_base: { type: 'string', enum: ['0', '1'], description: '报告用的坐标体系（默认 1；start_0/end_0 字段始终 0-based）' },
    },
    op: 'guide_enumerate',
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_score',
    description:
      '对已有的 sgRNA 候选列表补打 on-target 评分向量（供 graft_rank / graft_plan_save 消费）。' +
      '如 candidates 来自 graft_design 则直接原样传回；也可传裸序列字符串列表。' +
      '每个候选返回 gc_content/gc_class/homopolymer_runs/max_self_palindrome/u6_start_pref/' +
      'seed_8nt_pam_proximal + warnings（极端 GC/自回文/同聚物/长度异常），**不打综合分**。' +
      '触发词：打分、评分、on-target 分、guide 评分。',
    parameters: {
      candidates: { type: 'array', required: true, description: 'graft_design 返回的 candidates 数组（含 protospacer 字段）', items: { type: 'object', additionalProperties: true } },
      editor: { type: 'string', description: '编辑酶名（默认 SpCas9）' },
    },
    op: 'guide_score',
    timeoutMs: 60_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_offtarget',
    description:
      '用 Cas-OFFinder（BSD-3 官方二进制，v2.4.1）做批量脱靶扫描，返回**结构化命中**。' +
      '输入：genome_file（参考基因组 FASTA 文件或含 FASTA 的目录，绝对路径）+ 待查位点，' +
      '待查位点三选一：① candidates（**推荐**：graft_design 的原样输出，自动派生 spacer+PAM 与 PAM pattern）；' +
      '② queries（显式 spacer+PAM 字面量列表）；③ pattern（配合 queries 用，如 N20NGG）。' +
      '每条命中返回 chromosome / position_0based / position_1based / matched_sequence（错配碱基小写）/' +
      'strand / mismatches / mismatch_positions_1based。' +
      'preflight_only=true 时只做基因组体检（记录数/总 bp/N 比例/是否 CRLF）不扫描——' +
      '**长扫描前建议先 preflight**。device 默认 auto（本机若没有 CPU OpenCL 设备会自动改用 GPU 并回显实际设备）。' +
      '⚠️ **铁律：本工具的结果不能得出「安全」/「无脱靶」结论**——只能说' +
      '「在当前搜索参数下未检出高分位点」；n_hits=0 时返回 zero_hit_warning 列明常见假阴性原因，' +
      '必须排查而不是报平安。返回值始终带 interpretation_boundary（机器可读边界声明）。' +
      'bulge 搜索不受支持（Cas-OFFinder 本体需独立包装脚本），请求 bulge 会响亮报错。' +
      '触发词：脱靶、off-target、cas-offinder、特异性检查、全基因组扫描。',
    parameters: {
      genome_file: { type: 'string', required: true, description: '参考基因组 FASTA 文件或目录（绝对路径；上游可用 genie 的 bio_ref_genome/bio_entrez_fetch 获取）' },
      candidates: { type: 'array', items: { type: 'object', additionalProperties: true }, description: 'graft_design 返回的 candidates（推荐用法，自动派生 query 与 pattern）' },
      queries: { type: 'array', items: { type: 'string' }, description: '显式 spacer+PAM 序列列表（3prime PAM 为 spacer+PAM；5prime PAM 为 PAM+spacer）' },
      pattern: { type: 'string', description: "Cas-OFFinder pattern（须与 query 等长；支持 N20NGG 简写，工具内部展开）" },
      editor: { type: 'string', description: 'candidates 模式下用于派生 pattern 的编辑酶名（默认 SpCas9）' },
      mismatches: { type: 'number', description: '允许 mismatch 数（默认 3）' },
      device: { type: 'string', description: "OpenCL 设备：auto（默认，自动选择可用设备）/ C（CPU）/ G0,G1（GPU）" },
      top_n: { type: 'number', description: '最多返回命中数（默认 200；超出置 hits_truncated=true）' },
      preflight_only: { type: 'boolean', description: 'true=只做基因组体检不扫描（默认 false）' },
      output: { type: 'string', description: '命中原始输出路径（缺省写 ~/.dsh/dsh-bio-graft/tmp/）' },
    },
    op: 'offtarget_scan',
    timeoutMs: 1_800_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_backend_status',
    description:
      'graft 后端探测与安装：action=status 探测 Cas-OFFinder 可执行文件（GRAFT_CAS_OFFINDER env → ' +
      '~/.dsh/dsh-bio-graft/bin/ → PATH → 插件目录四处）；action=devices 列出 OpenCL 设备（判断能否扫描、' +
      '该用哪个 device）；action=ensure 自动下载官方 BSD-3 Windows x86-64 二进制（v2.4.1，约 180KB，' +
      '仅在 Windows 可用；非 Windows 明确拒绝）。' +
      '未来 provider（FlashFry/PrimeDesign/CRISPResso2 均为 GPL/学术专用许可，**永不 bundle**）也只走 external adapter。' +
      '触发词：后端状态、安装 cas-offinder、探测后端、OpenCL 设备、为什么扫描失败。',
    parameters: {
      action: { type: 'string', enum: ['status', 'devices', 'ensure'], description: 'status=探测；devices=列设备；ensure=缺则自动下载安装' },
    },
    async execute(args) {
      if (args.action === 'ensure') {
        return callGraft('offtarget_ensure', {}, { timeoutMs: 300_000 })
      }
      if (args.action === 'devices') {
        return callGraft('offtarget_devices', {}, { timeoutMs: 60_000 })
      }
      return callGraft('offtarget_backend', args, { timeoutMs: 60_000 })
    },
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_plan_save',
    description:
      '创建/追加 EditPlan（.editplan.json，graft 的核心资产锚点——append-only runs 账本，' +
      '面向编辑设计，回答「为什么昨天推荐 B、今天推荐 D」）。' +
      'action=new：创建计划（intent/reference/editor_profile 建议传；同名计划已存在时会拒绝覆盖，' +
      '防止重写审计历史）；action=add_run：追加一条 run（所有传入字段都会记录，不静默丢弃）；' +
      'action=update_recommendation：用 candidates 列表更新主 plan 的当前推荐（排序由 graft_rank/上层完成）。' +
      '所有修改都是**追加新的 run 记录**而不覆盖，run 号单调只增。' +
      '触发词：保存方案、编辑计划、EditPlan、编辑账本、记录方案。',
    parameters: {
      plan_name: { type: 'string', required: true, description: '计划名（只允许 [A-Za-z0-9._-]，如 TP53_demo_KO）' },
      action: { type: 'string', enum: ['new', 'add_run', 'update_recommendation'], description: '动作，默认 new' },
      intent: { type: 'object', additionalProperties: true, description: 'action=new 时必传：{target, desired_change, modality}' },
      reference: { type: 'object', additionalProperties: true, description: '{organism, assembly, sequence_hash, annotation_version}' },
      editor_profile: { type: 'object', additionalProperties: true, description: '编辑器配置（来自 graft_profiles）' },
      candidates: { type: 'array', items: { type: 'object', additionalProperties: true }, description: '候选列表（add_run 或 update_recommendation 用）' },
      ranking_policy: { type: 'object', additionalProperties: true, description: '声明式排序策略（objective/weights/tie_breakers/hard_filters）——推荐理由的审计依据' },
      off_target_summary: { type: 'object', additionalProperties: true, description: '脱靶扫描摘要（graft_offtarget 的 search_parameters + per-guide 计数 + interpretation_boundary）' },
      validation_plan: { type: 'object', additionalProperties: true, description: '验证计划（add_run 用）' },
      risk_flags: { type: 'array', items: { type: 'string' }, description: '风险 flag 列表' },
      provenance: { type: 'object', additionalProperties: true, description: '谁/什么工具/什么参数产生了这些数据（自动审计）' },
    },
    op: 'plan_create',
    timeoutMs: 60_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_plan_load',
    description:
      '读回一个 EditPlan：主 plan + 完整 runs/ 时间线（每条 run 一份 JSON，可回答' +
      '「为什么 guide B 昨天排名第一今天 guide D？」——reference / backend / ranking_policy ' +
      '的变更全部在 runs 里留痕）。可用 plan_path（绝对路径）或 plan_name（默认 plans 目录）指定。' +
      '触发词：读回方案、看方案历史、EditPlan 内容、编辑账本。',
    parameters: {
      plan_path: { type: 'string', description: '.editplan.json 绝对路径（来自 graft_plan_save 返回值）' },
      plan_name: { type: 'string', description: '计划名（与 plan_path 二选一；默认在 ~/.dsh/dsh-bio-graft/plans/ 下查找）' },
    },
    op: 'plan_load',
    timeoutMs: 60_000,
  })))

  ctx.effect(() => () => disposers.forEach((d) => d?.()), 'dsh-bio-graft: tools disposal')
}
