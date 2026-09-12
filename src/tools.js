// dsh-bio-graft — 工具层（v0.1：6 个语义化工具，2026-09-12 MVP 按评审裁决切法）
// 全部执行走 python/graft_ops.py（JSON stdin 协议）；Cas-OFFinder 由 offtarget.py
// 调外部 BSD-3 二进制（graft 不 bundle）。
//
// v0.1 op 一览（生命周期 TARGET→DESIGN→RANK→VERIFY→AUDIT）：
//   graft_profiles        — 列出内置 NucleaseProfile（编辑酶注册表）
//   graft_design          — sgRNA 枚举 + 评分向量（不打综合分）
//   graft_offtarget       — Cas-OFFinder 脱靶扫描（外部二进制）
//   graft_backend_status  — 后端探测（Cas-OFFinder / future providers）
//   graft_plan_save       — EditPlan 保存/追加 run（append-only 账本）
//   graft_plan_load       — EditPlan 读回（plan + 全部 runs 时间线）
import { defineTool } from '@deepseek-ai/dsh-tools'
import { isAbsolute } from 'node:path'
import { callGraft, stampProvenance } from './python.js'
import { ensureCasoffinder } from '../python/offtarget.js'

/** graft_ops 通用工具工厂（ graft op 全部直接透传 JSON）。 */
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
      '返回每个 profile 的：PAM 规则、PAM 位置（5/3prime）、靶标类型（DNA/RNA）、切口几何、' +
      '支持的 scoring 文献引用（不内置综合分）。选编辑器/查 PAM 之前先跑本工具。' +
      '触发词：编辑酶、 Cas9、Cas12、有哪些编辑器、PAM 规则。',
    parameters: {},
    op: 'profile_list',
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_design',
    description:
      'sgRNA 候选枚举 + on-target **评分向量**（v0.1 MVP）。输入目标序列（FASTA 或裸 DNA）+ 编辑酶名，' +
      '按 NucleaseProfile 的 PAM 语法双向扫描，返回 GuideCandidate 列表（protospacer/PAM/坐标/正负链）并附'
      + '评分向量（gc_content / gc_class / homopolymer_runs / max_self_palindrome / u6_start_pref /'
      + ' seed_8nt_pam_proximal + warnings）——**不打综合分**：rank 必须由 graft_plan_save 按 objective 完成，'
      + '「87.3 分」是伪精确，禁止向用户只报一个分数。' +
      '触发词：设计 sgRNA、找 guide、候选 sgRNA、编辑位点设计、crispr 设计。',
    parameters: {
      sequence: { type: 'string', required: true, description: '目标序列（FASTA 或裸 DNA 字符串，支持多олько 行）' },
      editor: { type: 'string', description: '编辑酶名，如 SpCas9/Cas12a/SpG（默认 SpCas9；先用 graft_profiles 查）' },
      top_n: { type: 'number', description: '返回 top_n 候选（默认 100; 按 start 坐标排序取前 N）' },
      position_base: { type: 'string', enum: ['0', '1'], description: '坐标位数（默认 1-based 报告，start_0/end_0 字段始终 0-based 半开区间）' },
    },
    op: 'guide_enumerate',
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_score',
    description:
      '对已有的 sgRNA 候选列表打 on-target 评分向量（供 graft_plan_save 消费）。' +
      '如 candidates 来自 graft_design 则直接传回；只需单独评分时也行。' +
      '每个候选返回 gc_content/gc_class/homopolymer_runs/max_self_palindrome/u6_start_pref/seed_marker' +
      ' + warnings（extreme GC/自回文/同聚物），**不打综合分**。' +
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
      '用 Cas-OFFinder（BSD-3 官方 Windows 二进制 v2.4.1）做批量脱靶扫描。' +
      '需要：1) pattern_file——Cas-OFFinder 原生模式文件（如「N20NGG」一行）；' +
      '2) genome_file——*已准备好的* 参考基因组多 FASTA（graft 不代用户准备，错误时明确报）。' +
      '输出：Cas-OFFinder 原始命中行（Bulge type/DNA/RNA/Chromosome/Position 等）——' +
      'graft 后续版本加 CRISPR 语义解释层（mismatch 分布/功能注释/风险分级）。' +
      '**铁律：本工具的结果不能得出「安全」/「无脱靶」结论**，只可说' +
      '「在当前搜索参数下未检出高分位点」——这是 skill 硬规则。' +
      '触发词：脱靶、off-target、cas-offinder、特异性检查。',
    parameters: {
      pattern_file: { type: 'string', required: true, description: 'Cas-OFFinder 模式文件绝对路径（每行一个，如 N20NGG）' },
      genome_file: { type: 'string', required: true, description: '参考基因组多 FASTA 绝对路径' },
      mismatches: { type: 'number', description: '允许 mismatch 数（默认 3）' },
      dna_bulge: { type: 'number', description: 'DNA bulge 大小（默认 0）' },
      rna_bulge: { type: 'number', description: 'RNA bulge 大小（默认 0）' },
      output: { type: 'string', description: '命中输出路径（缺省走临时文件）' },
      top_n: { type: 'number', description: '最多返回前 N 行（默认 200）' },
    },
    op: 'offtarget_scan',
    timeoutMs: 1_800_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_backend_status',
    description:
      'graft 后端探测（install status/action）：Cas-OFFinder 是否可用（GRAFT_CAS_OFFINDER 环境变量、' +
      '~/.dsh/dsh-bio-graft/bin/、PATH 三处）；action=ensure 时自动下载官方 BSD-3 Windows 二进制'
      + ' Cas-OFFinder v2.4.1（约 180KB）。未来 provider（FlashFry/PrimeDesign/CRISPResso2 都是' +
      ' GPL/academic-only，**永不 bundle**，只走 external adapter）也在此列出。' +
      '触发词：后端状态、安装 cas-offinder、探测后端。',
    parameters: {
      action: { type: 'string', enum: ['status', 'ensure'], description: 'status=只探测；ensure=确保安装（缺则自动下载）' },
    },
    async execute(args) {
      if (args.action === 'ensure') {
        const r = await ensureCasoffinder()
        return stampProvenance('graft_backend_status', r)
      }
      return callGraft('offtarget_backend', args, { timeoutMs: 60_000 })
    },
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_plan_save',
    description:
      '创建/追加 EditPlan（.editplan.json，graft 的核心资产锚点——' +
      'append-only runs 账本，类似 gem 的 ledger 但面向编辑设计）。' +
      'action=new：创建计划（intent/reference/editor_profile 需传）；' +
      'action=add_run：追加一条 run（如 guide 枚举结果 / off-target 结果 / 重新排序）；' +
      'action=update_recommendation：用 candidates 列表更新主 plan 的当前推荐（排序由 agent/上层做）。' +
      '所有修改都是**追加新的 run 记录**而不覆盖——这是审计需要的。' +
      '触发词：保存方案、编辑计划、EditPlan、编辑账本、记录方案。',
    parameters: {
      plan_name: { type: 'string', required: true, description: '计划名（如 TP53_demo_KO，安全字符 [a-zA-Z0-9-_.]）' },
      action: { type: 'string', enum: ['new', 'add_run', 'update_recommendation'], description: '动作，默认 new' },
      intent: { type: 'object', additionalProperties: true, description: 'action=new 时必传：{target, desired_change, modality}' },
      reference: { type: 'object', additionalProperties: true, description: '{organism, assembly, sequence_hash, annotation_version}' },
      editor_profile: { type: 'object', additionalProperties: true, description: '编辑器配置（来自 graft_profiles）' },
      candidates: { type: 'array', items: { type: 'object', additionalProperties: true }, description: '候选列表（add_run 或 update_recommendation 用）' },
      validation_plan: { type: 'object', additionalProperties: true, description: '验证计划（add_run 用）' },
      risk_flags: { type: 'array', items: { type: 'string' }, description: '风险 flag 列表' },
      provenance: { type: 'object', additionalProperties: true, description: '谁/什么工具/什么参数产生的这些数据（自动审计）' },
    },
    op: 'plan_create',
    timeoutMs: 60_000,
  })))

  disposers.push(ctx.tools.register(graftTool({
    name: 'graft_plan_load',
    description:
      '读回一个 EditPlan：主 plan + 完整 runs/ 时间线（每条 run 一份 JSON，' +
      '可回答「为什么 guide B 昨天排名第一今天 guide D？」——因为 reference / backend /' +
      ' ranking policy 变更全部在 runs 里留痕）。' +
      '触发词：读回方案、看方案历史、EditPlan 内容。',
    parameters: {
      plan_path: { type: 'string', required: true, description: '.editplan.json 绝对路径（来自 graft_plan_save 返回）' },
    },
    op: 'plan_load',
    timeoutMs: 60_000,
  })))

  ctx.effect(() => () => disposers.forEach((d) => d?.()), 'dsh-bio-graft: tools disposal')
}
