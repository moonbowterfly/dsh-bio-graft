"""validation.py — 验证方案（ValidationRequirement[]，批次 F）。

═══════════════════════════════════════════════════════════════════════════
设计纪律（GPT 裁决 #11/#18 + 用户「两层生成契约」）
═══════════════════════════════════════════════════════════════════════════
1. **不给一套万能 protocol**：给 `ValidationRequirement[]`，按模态与宿主类型分档
   （required / recommended / conditional），每条含「测什么、回答什么问题、为什么」。
2. **两层生成契约**：Layer 1 = 代码算出的**事实型要求**（assay、要报告的指标、分子/分母定义、
   必须区分的产物类别）；Layer 2 = agent 结合实验室现实（试剂盒、预算、通量）具体化，
   改动标 [推断]。硬约束（不能少的关键测量）不可删。
3. **EditOutcomeMetrics 必须带分子/分母/assay**：禁止裸 `efficiency = 43`——
   「产生 indel 的读段 / 质控后读段」这类定义必须随数字出现（GPT 裁决 #10）。
4. **植物不作默认**：宿主类型由调用方声明；植物额外出现嵌合/倍性/可遗传/载体残留等项。
5. **诚实边界**：返回值带 `cannot_conclude`（本方案不能证明什么），并把「效率不预测」
   与「脱靶结论边界」写进去。
"""
from __future__ import annotations

MODALITIES: dict[str, dict] = {
    'nuclease_ko': {
        'zh': '核酸酶敲除（NHEJ indel）',
        'required': ['on_target_amplicon', 'allele_composition'],
        'recommended': ['protein_level_knockout', 'clone_isolation'],
        'conditional': ['nominated_offtarget', 'large_deletion_longread', 'karyotype_check'],
    },
    'base_edit': {
        'zh': '碱基编辑（CBE/ABE）',
        'required': ['on_target_amplicon', 'outcome_spectrum', 'bystander_quantification',
                     'indel_fraction'],
        'recommended': ['protein_level_change', 'clone_isolation'],
        'conditional': ['nominated_offtarget', 'rna_offtarget', 'splice_site_check'],
    },
    'deletion_pair': {
        'zh': '双 guide 缺失（deletion_pair）',
        'required': ['junction_pcr', 'deletion_size_verification', 'absence_of_deleted_segment',
                     'outcome_spectrum'],
        'recommended': ['clone_isolation', 'protein_level_knockout'],
        'conditional': ['nominated_offtarget', 'translocation_assay', 'long_read_haplotyping'],
    },
    'paired_nickase': {
        'zh': '配对切口酶',
        'required': ['on_target_amplicon', 'outcome_spectrum'],
        'recommended': ['allele_composition', 'clone_isolation'],
        'conditional': ['nominated_offtarget', 'large_deletion_longread'],
    },
    'hdr': {
        'zh': 'HDR 供体敲入',
        'required': ['both_junctions', 'internal_intended_edit', 'wildtype_allele_discrimination'],
        'recommended': ['protein_level_expression', 'clone_isolation', 'donor_integrity'],
        'conditional': ['backbone_random_integration', 'karyotype_check'],
    },
    'multiplex_knockout': {
        'zh': '多重敲除（多靶点）',
        'required': ['per_target_on_target', 'allele_composition'],
        'recommended': ['clone_isolation'],
        'conditional': ['nominated_offtarget', 'karyotype_check', 'translocation_assay'],
    },
}

ASSAYS: dict[str, dict] = {
    'on_target_amplicon': {
        'zh': '靶点扩增子测序（NGS 或 Sanger+TIDE/ICE）',
        'question': '编辑是否发生？indel/替换比例是多少？',
        'why': '所有模态的最低共同要求：先证明在靶点发生了改变，再谈功能后果。',
        'handoff': '引物用 genie 的 bio_primer3_design（在靶点两侧 150–300 bp 处设计）',
    },
    'allele_composition': {
        'zh': '等位基因组成（克隆/单细胞层面）',
        'question': '双等位、单等位、野生型各占多少？',
        'why': '混合群体测序无法区分「双等位 KO」与「单等位 KO + 未编辑等位」——表型解释完全不同。',
        'handoff': '挑单克隆后逐个测序；或长读单分子定相',
    },
    'outcome_spectrum': {
        'zh': '全产物谱（相对目标产物分别定量）',
        'question': '目标产物 / 目标+bystander / 非目标转换 / indel / 野生型 各占多少？',
        'why': '只报单一「编辑效率」会掩盖共存产物；碱基编辑与双 guide 缺失尤其明显。',
        'handoff': '扩增子 NGS + CRISPResso2 类分析（external adapter，不随本插件分发）',
    },
    'bystander_quantification': {
        'zh': 'bystander 定量',
        'question': '窗口内其他同底物碱基被编辑的比例？',
        'why': 'bystander 决定产物纯度与功能解释；graft_base_edit 已列出窗口内所有同底物碱基，'
                '验证必须逐位点定量。',
        'handoff': '扩增子 NGS 后按位点拆解等位型',
    },
    'indel_fraction': {
        'zh': 'indel 分数',
        'question': '除目标替换外，是否伴随 indel？',
        'why': '碱基编辑号称「不产生 DSB」，但实测常有 indel；不报就会高估纯度。',
        'handoff': '扩增子 NGS 读段比对',
    },
    'protein_level_knockout': {
        'zh': '蛋白水平确认（Western / 抗体 / 功能读数）',
        'question': '蛋白是否真的缺失/失活？',
        'why': '移码不等价于无蛋白：可能产生截短体或从下游 ATG 重新起始；'
                '「基因型敲除」≠「功能敲除」。',
        'handoff': 'Western blot 或功能表型读数',
    },
    'protein_level_change': {
        'zh': '蛋白水平/功能确认',
        'question': '氨基酸改变是否带来预期的功能变化？',
        'why': 'nonsense 可能触发 NMD 也可能不触发；missense 的功能后果需实测。',
        'handoff': 'Western / 活性测定',
    },
    'protein_level_expression': {
        'zh': '表达确认（敲入产物）',
        'question': '敲入的序列是否表达？表达量如何？',
        'why': '基因组整合 ≠ 表达；需 mRNA（RT-qPCR）与蛋白两层。',
        'handoff': 'RT-qPCR + Western / 报告基因读数',
    },
    'junction_pcr': {
        'zh': '连接点 PCR（跨预测 junction 的正/反向引物）',
        'question': '预测的连接点是否真实存在？',
        'why': '缺失事件的核心证据：引物应跨预测 junction，野生型应不出条带（或出更大条带）。',
        'handoff': '引物用 genie 的 bio_primer3_design；graft_strategy 已给出 junction 规则',
    },
    'deletion_size_verification': {
        'zh': '缺失大小验证（片段长度或长读）',
        'question': '实际缺失长度是否等于预测值？',
        'why': '实际缺失边界常与切点预测不一致（修复路径多样），必须实测长度而非假定。',
        'handoff': '凝胶/Sanger 测连接点序列/长读',
    },
    'absence_of_deleted_segment': {
        'zh': '被删区段缺失确认（区段内侧引物应无产物）',
        'question': '被删的那一段确实不在了？',
        'why': '排除杂合缺失与等位混杂（未编辑等位仍会给出产物）。',
        'handoff': '区段内侧引物对做阴性对照',
    },
    'both_junctions': {
        'zh': '双侧连接点测序（5′ 与 3′ 各一）',
        'question': '供体两侧是否正确连接？',
        'why': 'HDR 最常见的失败是单侧正确、另一侧随机整合——只测一侧会漏。',
        'handoff': '跨臂引物 + 连接点 Sanger/长读',
    },
    'internal_intended_edit': {
        'zh': '供体内部目标编辑确认',
        'question': '目标序列（含预期突变）是否完整写入？',
        'why': '连接正确不等于内部序列正确（可能有重组/合成错误）。',
        'handoff': '供体内部测序',
    },
    'wildtype_allele_discrimination': {
        'zh': '野生型等位区分',
        'question': '是否残留野生型等位？',
        'why': '杂合敲入与纯合敲入的表型解释不同。',
        'handoff': '等位特异 PCR/测序',
    },
    'donor_integrity': {
        'zh': '供体完整性（是否有骨架/载体序列混入）',
        'question': '插入的是「干净供体」还是带骨架的载体片段？',
        'why': '质粒供体常整合骨架，影响后续表达与安全评估。',
        'handoff': '骨架引物做阴性检查',
    },
    'nominated_offtarget': {
        'zh': '提名脱靶位点验证（对算法预测的高分位点做定点测序）',
        'question': '预测的高风险位点是否真的被编辑？',
        'why': '计算「未检出」不等于体内发生（反之亦然）——验证必须落到具体位点。',
        'handoff': 'graft_offtarget 给出候选位点 → 逐个扩增测序',
    },
    'large_deletion_longread': {
        'zh': '大片段缺失/重排检查（长读或数字 PCR）',
        'question': '是否出现超出预期的缺失/重排？',
        'why': '单个切点也可能产生大片段缺失；短读测序容易漏。',
        'handoff': '长读测序 / ddPCR',
    },
    'karyotype_check': {
        'zh': '核型/染色体稳定性检查',
        'question': '是否出现非整倍体或大尺度异常？',
        'why': '多重编辑与多次传代后基因组稳定性可能下降。',
        'handoff': '核型分析 / CNV 检测',
    },
    'translocation_assay': {
        'zh': '易位检测（跨位点融合）',
        'question': '多个切点之间是否发生易位？',
        'why': '双 guide 与多重编辑的独有风险：两个位点的 DSB 可能相互连接。',
        'handoff': '跨位点引物对 / 长读',
    },
    'long_read_haplotyping': {
        'zh': '长读单分子定相',
        'question': '多重改变是否落在同一条染色体上？',
        'why': '确定连锁关系（顺式/反式）需要单分子长度。',
        'handoff': '长读测序',
    },
    'per_target_on_target': {
        'zh': '逐靶点在靶验证',
        'question': '每个靶点各自编辑比例多少？',
        'why': '多重敲除的效率常不均一，必须逐靶点报告，不能给一个平均值。',
        'handoff': '每个靶点一套扩增子',
    },
    'clone_isolation': {
        'zh': '单克隆分离与传代稳定性',
        'question': '编辑能否在单克隆中稳定传代？',
        'why': '群体水平的结果可能来自瞬时/嵌合事件，单克隆化才能确定可遗传性。',
        'handoff': '有限稀释/挑单克隆 → 传 1–2 代后复测',
    },
    'rna_offtarget': {
        'zh': 'RNA 层面脱靶（转录组）',
        'question': '是否出现预期外的转录本改变（含剪接）？',
        'why': '碱基编辑器在 RNA 上也有脱氨活性（尤其 CBE），且有广泛 RNA 编辑报道。',
        'handoff': 'RNA-seq + 变异检出',
    },
    'splice_site_check': {
        'zh': '剪接位点检查',
        'question': '编辑是否落在/影响剪接位点？',
        'why': '外显子边界附近的编辑可能改变剪接，产生意料外的转录本。',
        'handoff': 'RT-PCR 剪接产物 + 测序',
    },
}

HOST_EXTRAS: dict[str, list[dict]] = {
    'plant': [
        {'id': 'mosaicism_chimerism', 'tier': 'required', 'zh': '嵌合/杂合状态检查',
         'question': '同一株体内是否存在未编辑细胞谱系？',
         'why': '植物转化常得到嵌合体（T0）：以 T0 表型直接下结论会系统性高估编辑效果。'},
        {'id': 'zygosity', 'tier': 'required', 'zh': '合子性判定',
         'question': '杂合/纯合/双等位？',
         'why': '后代分离与育种决策取决于合子性。'},
        {'id': 'heritable_transmission', 'tier': 'recommended', 'zh': '可遗传性（T1 传递）',
         'question': '编辑能否传递给下一代？',
         'why': '植物编辑的落地价值取决于可遗传性；T0 检测不足以判定。'},
        {'id': 'transgene_persistence', 'tier': 'conditional', 'zh': '载体/转基因残留（尤其 DNA 递送）',
         'question': '编辑体是否残留外源 DNA？',
         'why': 'RNP 递送与质粒递送的合规与育种后果不同；DNA 递送需检查残留。'},
    ],
    'animal': [
        {'id': 'germline_transmission', 'tier': 'recommended', 'zh': '生殖系传递',
         'question': '编辑是否进入生殖系？', 'why': '影响传代与伦理评估。'},
        {'id': 'offtarget_wholegenome', 'tier': 'conditional', 'zh': '全基因组脱靶（WGS/WES）',
         'question': '是否有低比例的非提名脱靶？',
         'why': '提名验证只覆盖预测位点；高风险应用需无偏检测。'},
    ],
}

OUTCOME_METRICS = [
    {'metric': 'target_modification_rate', 'numerator': '含任何目标位点改变的读段',
     'denominator': '质控后读段总数', 'assay': 'amplicon_ngs'},
    {'metric': 'desired_product_rate', 'numerator': '恰好等于预期基因型的读段',
     'denominator': '质控后读段总数', 'assay': 'amplicon_ngs'},
    {'metric': 'product_purity', 'numerator': '预期基因型读段',
     'denominator': '所有含目标位点改变的读段', 'assay': 'amplicon_ngs',
     'note': '与 desired_product_rate 的分母不同——报告时必须说明用的是哪个'},
    {'metric': 'indel_rate', 'numerator': '含 indel 的读段', 'denominator': '质控后读段总数',
     'assay': 'amplicon_ngs'},
    {'metric': 'bystander_rate', 'numerator': '窗口内非目标碱基也被编辑的读段',
     'denominator': '含目标编辑的读段', 'assay': 'amplicon_ngs'},
    {'metric': 'biallelic_rate', 'numerator': '双等位均改变的克隆数',
     'denominator': '受检克隆数', 'assay': 'single_clone_genotyping'},
    {'metric': 'functional_edit_rate', 'numerator': '蛋白/表型层面确认改变的克隆数',
     'denominator': '基因型阳性克隆数', 'assay': 'protein_or_phenotype'},
    {'metric': 'viability', 'numerator': '存活细胞/植株数', 'denominator': '处理细胞/植株数',
     'assay': 'count'},
]

CANNOT_CONCLUDE = [
    '本方案不能预测编辑效率——效率是实验量（EditOutcomeMetrics 由实测填充）。',
    '本方案不能给出「安全」结论：即使全部提名位点为阴性，也只说明「在这些位点、这个检测灵敏度下未检出」。',
    '本方案不替代伦理/合规审查（尤其涉及可遗传编辑与释放试验）。',
    '验证计划由代码给事实型要求（Layer 1）；落到具体试剂/预算/通量时由 agent 结合现实改写并标 [推断]（Layer 2），'
    '但 required 档的关键测量不可删除。',
]


def build_validation_plan(modality: str, *, host_type: str = 'cell_line',
                          delivery: str | None = None, notes: str = '') -> dict:
    """生成验证方案（ValidationRequirement[] + EditOutcomeMetrics + 边界声明）。"""
    m = MODALITIES.get(modality)
    if m is None:
        raise ValueError(f'unknown modality {modality!r}；可用：{sorted(MODALITIES)}')

    def rows(ids, tier):
        out = []
        for i in ids:
            a = ASSAYS.get(i)
            if a is None:
                continue
            out.append({'id': i, 'tier': tier, 'zh': a['zh'], 'question': a['question'],
                        'why': a['why'], 'handoff': a.get('handoff')})
        return out

    required = rows(m['required'], 'required')
    recommended = rows(m['recommended'], 'recommended')
    conditional = rows(m['conditional'], 'conditional')

    extras = HOST_EXTRAS.get(host_type, [])
    for e in extras:
        row = {'id': e['id'], 'tier': e['tier'], 'zh': e['zh'], 'question': e['question'],
               'why': e['why'], 'handoff': None, 'host_specific': host_type}
        {'required': required, 'recommended': recommended, 'conditional': conditional}[e['tier']].append(row)

    warnings = []
    if delivery == 'dna' and host_type == 'plant':
        warnings.append('DNA 递送 + 植物：必须检查载体/转基因残留（transgene_persistence）')
    if modality == 'base_edit':
        warnings.append('碱基编辑必须逐位点定量 bystander——不要只报一个「编辑效率」')

    return {
        'modality': modality,
        'modality_zh': m['zh'],
        'host_type': host_type,
        'delivery': delivery,
        'required': required,
        'recommended': recommended,
        'conditional': conditional,
        'outcome_metrics': OUTCOME_METRICS,
        'metrics_note': ('每个指标必须带 numerator/denominator/assay 一起报告——'
                         '禁止裸「efficiency = 43」；不同指标的分母不同（见 note）。'),
        'handoff_summary': {
            'primers': '引物设计走 genie 的 bio_primer3_design（本插件不重复实现）',
            'junction': '双 guide 缺失的连接点规则来自 graft_strategy（junction_rule 字段）',
            'offtarget_nomination': '提名位点来自 graft_offtarget（per_guide + hits）',
        },
        'generation_contract': {
            'layer1_facts': '本文件给出的 assay/指标/分子分母定义/必须区分的产物类别（不可删）',
            'layer2_agent': 'agent 结合实验室现实（试剂盒、预算、通量、物种材料）具体化为可执行清单，'
                            '改动处标 [推断]；required 档的关键测量不可删除，只可替换为等效手段',
        },
        'cannot_conclude': CANNOT_CONCLUDE,
        'notes': ([notes] if notes else []) + warnings,
    }
