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
      '列出内置编辑酶/NucleaseProfile（graft 的语义基石，所有下游都从 profile 读）与**碱基编辑器**' +
      '（BaseEditorProfile，五层结构）。' +
      'Nuclease 每个 profile 返回：PAM 模式（IUPAC，如 NGG/TTTV）、PAM 位置（3prime/5prime）、' +
      'spacer 长度、切点偏移与结构（blunt/staggered）、评分文献引用，以及 **verified / pam_source ' +
      '证据分级**——verified=false 表示该 PAM/几何尚未对一手文献核对，报告里必须如实转述，' +
      '不得当作既定事实。碱基编辑器返回 targeting/chemistry/activity/evidence/applicability 五层' +
      '（窗口编号约定：位置 1 = PAM-distal 端，PAM 记为 21–23）+ window_evidence 引用。' +
      '选编辑器/查 PAM 或编辑窗口之前先跑本工具。' +
      '触发词：编辑酶、Cas9、Cas12、有哪些编辑器、PAM 规则、spacer 长度、切割位点、碱基编辑器、CBE、ABE、编辑窗口。',
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
      '**批次 C 起返回结构化语义**：① search_completeness——**枚举哪些维度没搜**' +
      '（dna_bulge/rna_bulge/structural_variation/sample_variants 恒为 not_searched；' +
      '「没搜」≠「搜了没命中」）；② assessment.safety_conclusion 恒为 not_supported' +
      '（API 里不存在 safe:true / risk_level，禁词清单见 forbidden_phrasing）；' +
      '③ per_guide——每条 query 的命中数/mismatch 分布/seed 区命中数/最近位点/是否含精确匹配。' +
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

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_rank',
    description:
      '按**声明式策略**给候选排名（graft_rank）—— 不产生综合分/质量分，只回答' +
      '「在声明的策略下 A 是否优于 B」，并把整个 policy 随结果一起返回（policy_id + policy_digest），' +
      '供 graft_plan_save 的 ranking_policy 字段落账本（回答「为什么昨天 B 今天 D」）。' +
      '三种策略：pareto（默认，支配关系：不引入价值偏好时唯一客观的表达，返回 pareto_front 与 ' +
      'dominated_by）、lexicographic（字典序，order=["template_hits:min","max_self_palindrome:min",' +
      '"gc_abs_dev:min"] 声明哪个 criterion 更重要）、weighted（**必须显式给 weights**，' +
      '否则报错；返回 declared_objective_value = 按声明权重的线性组合并附 disclaimer）。' +
      'hard_filters 支持硬约束（template_hits_max / gc_min|gc_max / max_self_palindrome_max / ' +
      'homopolymer_max_max / offtarget_total_max / offtarget_mm0_max… / exclude_warnings），' +
      '被剔除的候选带 reasons；**依赖的数据缺失时按 not_searched 处理并剔除说明——绝不静默通过**。' +
      '可用度量：template_hits / gc_content / gc_abs_dev / max_self_palindrome / homopolymer_max / ' +
      'cut_site_0 / offtarget_total / offtarget_mm0..3。' +
      '触发词：排序、排名、选最优 guide、多目标、Pareto、按什么排、挑一个 guide。',
    parameters: {
      candidates: { type: 'array', required: true, description: 'graft_design/graft_score 输出的候选数组（可含 graft_offtarget 回填的 offtarget_summary）', items: { type: 'object', additionalProperties: true } },
      policy: { type: 'string', enum: ['pareto', 'lexicographic', 'weighted'], description: '排序策略（默认 pareto）' },
      order: { type: 'array', items: { type: 'string' }, description: 'lexicographic 的度量序列，如 ["template_hits:min","gc_abs_dev:min"]' },
      objectives: { type: 'array', items: { type: 'string' }, description: 'pareto 的目标序列（默认 template_hits:min / max_self_palindrome:min / gc_abs_dev:min）' },
      weights: { type: 'object', additionalProperties: true, description: 'weighted 的显式权重 {metric: weight}（原始单位，不做默认加权）' },
      hard_filters: { type: 'object', additionalProperties: true, description: '硬约束，如 {template_hits_max:1, gc_min:0.35, gc_max:0.7}' },
      top_n: { type: 'number', description: '只返回前 N 名（excluded 仍全量返回）' },
    },
    op: 'rank_candidates',
    timeoutMs: 60_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_base_edit',
    description:
      '碱基编辑设计（CBE/ABE）：枚举碱基编辑候选——窗口内可编辑碱基 + bystander + 密码子后果。' +
      '**只做确定性几何**：目标碱基落在核心窗口内 = 「几何兼容」；本工具**不预测**编辑效率与产物纯度' +
      '（见返回体的 profile.applicability 与 geometry_vs_efficiency）。' +
      '内置编辑器（窗口均已核一手文献，返回值带五层结构 targeting/chemistry/activity/evidence/applicability）：' +
      'BE3、BE4max（CBE，C→T，窗口位置 4–8；Komor 2016 / Koblan 2018）、' +
      'ABE7.10（ABE，A→G，窗口位置 4–7；Gaudelli 2017）。' +
      '**窗口编号约定**：位置 1 = protospacer 的 PAM-distal 端，PAM 记为 21–23。' +
      '必须同时看三件套，否则反链 guide 会被说错：guide_strand / edited_physical_strand / ' +
      'reference_reported_substitution（例：反链 guide 的 C→T 在参考正链上表现为 **G→A**）。' +
      '窗口内第二个同底物碱基 = **bystander**（产物不纯），工具会列进 editable_positions 并给警告——' +
      '报告不能只写「实现了 C→T」。' +
      '密码子后果需显式声明 cds_start_0（未声明时返回 not_applicable，**不猜读码框**；' +
      'cds_strand="-" 当前不支持）。' +
      '触发词：碱基编辑、CBE、ABE、C→T、A→G、bystander、点突变、无义突变、终止密码子、碱基编辑器。',
    parameters: {
      sequence: { type: 'string', required: true, description: '目标序列（FASTA 或裸 DNA；编辑窗口按该序列的 + 链坐标报告）' },
      editor: { type: 'string', description: '碱基编辑器名（BE3 / BE4max / ABE7.10；默认 BE3；先用 graft_profiles 查）' },
      cds_start_0: { type: 'number', description: 'CDS 起点（0-based）；给了才算密码子后果（synonymous/missense/nonsense/stop_loss）' },
      cds_strand: { type: 'string', enum: ['+', '-'], description: 'CDS 所在链（默认 +；"-" 当前不支持密码子后果，会显式标注）' },
      strand: { type: 'string', enum: ['both', '+', '-'], description: '扫描哪条链（默认 both）' },
      include_broader_window: { type: 'boolean', description: 'true=用更宽的观测窗口（如 CBE 2–8）而非核心窗口（默认 false）' },
      top_n: { type: 'number', description: '返回候选数上限（默认 100；单碱基（无 bystander）的候选排前）' },
    },
    op: 'base_edit_design',
    timeoutMs: 120_000,
  })))

  ctx.effect(() => () => disposers.forEach((d) => d?.()), 'dsh-bio-graft: tools disposal')
}
