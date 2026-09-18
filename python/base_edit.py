"""base_edit.py — 碱基编辑设计（graft_base_edit）：窗口内可编辑碱基枚举 + bystander + 密码子后果。

═══════════════════════════════════════════════════════════════════════════
设计纪律（GPT 裁决 #5/#9 定稿）
═══════════════════════════════════════════════════════════════════════════
1. **只做确定性几何 + 明示证据边界**：目标碱基是否落在核心窗口内 = 几何事实；
   「会不会高效编辑」= 未验证预测，本工具**不输出**（详见 profile.applicability）。
2. **链语义必须三件套齐全**（否则反链 guide 迟早被说错）：
   `guide_strand` / `edited_physical_strand` / `reference_reported_substitution`
   （例：反链 guide 上的 C→T，在参考正链上表现为 **G→A**）。
3. **bystander 必须显式列出**：窗口内第二个同底物碱基会被一起编辑 → 产物不纯，
   报告里不能只写"成功实现 C→T"。
4. **转录本歧义**：`codon_effect` 依赖调用方声明的 CDS 起点与链；未声明时返回
   `not_applicable` 并说明缺什么，**绝不猜读码框**。反链 CDS 当前不支持（同样显式说明）。
"""
from __future__ import annotations

from base_editors import get_base_editor
from editors import get_editor
from guides import enumerate_guides
from sequtil import clean_sequence

# 标准遗传密码（NCBI 翻译表 1）
_CODON_TABLE = {
    'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L', 'CTT': 'L', 'CTC': 'L', 'CTA': 'L',
    'CTG': 'L', 'ATT': 'I', 'ATC': 'I', 'ATA': 'I', 'ATG': 'M', 'GTT': 'V', 'GTC': 'V',
    'GTA': 'V', 'GTG': 'V', 'TCT': 'S', 'TCC': 'S', 'TCA': 'S', 'TCG': 'S', 'CCT': 'P',
    'CCC': 'P', 'CCA': 'P', 'CCG': 'P', 'ACT': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T',
    'GCT': 'A', 'GCC': 'A', 'GCA': 'A', 'GCG': 'A', 'TAT': 'Y', 'TAC': 'Y', 'TAA': '*',
    'TAG': '*', 'CAT': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q', 'AAT': 'N', 'AAC': 'N',
    'AAA': 'K', 'AAG': 'K', 'GAT': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E', 'TGT': 'C',
    'TGC': 'C', 'TGA': '*', 'TGG': 'W', 'CGT': 'R', 'CGC': 'R', 'CGA': 'R', 'CGG': 'R',
    'AGT': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R', 'GGT': 'G', 'GGC': 'G', 'GGA': 'G',
    'GGG': 'G',
}

_COMPLEMENT = str.maketrans('ACGTN', 'TGCAN')

COORDINATE_SYSTEM = (
    'window/target 位置均为 **protospacer 内 1-based 编号，位置 1 = PAM-distal 端**，'
    'PAM 记为位置 21–23（Gaudelli 2017 原文约定）；genome_pos_* 为参考序列 + 链的 0-based 坐标'
)


def _complement(base: str) -> str:
    return base.translate(_COMPLEMENT)


def _codon_effect(seq: str, *, genome_pos_0: int, cds_start_0: int, edited_base: str) -> dict | None:
    """按声明的 CDS 起点计算密码子后果（只在 + 链 CDS 且位置落在 CDS 内时返回）。"""
    offset = genome_pos_0 - cds_start_0
    if offset < 0:
        return {'status': 'outside_cds', 'reason': f'位置在 CDS 起点上游（offset={offset}）'}
    codon_index = offset // 3
    codon_start = cds_start_0 + 3 * codon_index
    ref_codon = seq[codon_start:codon_start + 3]
    if len(ref_codon) < 3:
        return {'status': 'outside_cds', 'reason': '位置超出序列末端（无完整密码子）'}
    in_codon_offset = offset % 3
    alt_codon = ref_codon[:in_codon_offset] + edited_base + ref_codon[in_codon_offset + 1:]
    aa_ref = _CODON_TABLE.get(ref_codon)
    aa_alt = _CODON_TABLE.get(alt_codon)
    if aa_ref is None or aa_alt is None:
        return {'status': 'unknown_codon', 'ref_codon': ref_codon, 'alt_codon': alt_codon}
    if aa_ref == aa_alt:
        consequence = 'synonymous'
    elif aa_alt == '*' and aa_ref != '*':
        consequence = 'nonsense'
    elif aa_ref == '*' and aa_alt != '*':
        consequence = 'stop_loss'
    else:
        consequence = 'missense'
    return {
        'status': 'computed',
        'codon_index': codon_index,
        'codon_start_0': codon_start,
        'ref_codon': ref_codon,
        'alt_codon': alt_codon,
        'aa_ref': aa_ref,
        'aa_alt': aa_alt,
        'consequence': consequence,
    }


def design_base_edit(sequence: str, editor: str = 'BE3', *,
                     cds_start_0: int | None = None, cds_strand: str = '+',
                     strand: str = 'both', top_n: int = 100,
                     include_broader_window: bool = False) -> dict:
    """枚举碱基编辑候选：窗口内可编辑碱基 + bystander + 密码子后果（几何层，不做活性预测）。"""
    profile = get_base_editor(editor)
    seq, record_id, n_records = clean_sequence(sequence)
    nuclease = get_editor(profile.nuclease)
    lo, hi = profile.core_window if profile.core_window else (None, None)
    if lo is None:
        raise ValueError(f'{profile.name} 未声明核心窗口（未经一手文献核对）——拒绝设计')
    if strand not in ('both', '+', '-'):
        raise ValueError(f'strand 必须是 both / + / -，收到 {strand!r}')

    scan = enumerate_guides(seq, editor=profile.nuclease, top_n=10 ** 6,
                            # '-' 需要枚举反链；enumerate_guides 的 false 语义是只扫正链。
                            scan_both_strands=(strand in ('both', '-')))
    scanned = scan.get('candidates') or []
    candidates = (scanned if strand == 'both'
                  else [c for c in scanned if c.get('strand', '+') == strand])
    win_lo, win_hi = (profile.broader_observed_window if include_broader_window
                      else profile.core_window)

    out = []
    n_with_editable = 0
    for c in candidates:
        P = c.get('protospacer') or ''
        if len(P) != profile.spacer_length:
            continue
        g_strand = c.get('strand', '+')
        editable = []
        for pos in range(win_lo, min(win_hi, len(P)) + 1):
            base = P[pos - 1]
            if base != profile.substrate_base:
                continue
            if g_strand == '+':
                genome_pos_0 = c['start_0'] + (pos - 1)
            else:
                # 反链候选：protospacer 是反链 frame 的序列，其 index j 对应原链坐标 end_0-1-j
                genome_pos_0 = c['end_0'] - 1 - (pos - 1)
            ref_from = base if g_strand == '+' else _complement(base)
            ref_to = profile.product_base if g_strand == '+' else _complement(profile.product_base)
            entry = {
                'protospacer_pos_1based': pos,
                'physical_base': base,
                'edited_physical_strand': g_strand,
                'genome_pos_0based': genome_pos_0,
                'genome_pos_1based': genome_pos_0 + 1,
                'reference_reported_substitution': {'from': ref_from, 'to': ref_to},
                'product_base_on_protospacer': profile.product_base,
            }
            if cds_start_0 is not None:
                if cds_strand == '+':
                    # ⚠️ ref_to 已经是**参考 + 链**上的碱基（反链候选时 = complement(product)），
                    # 不能再次取互补 —— 早期版本多取一次互补，反链候选的密码子后果会算错（实测）。
                    entry['codon_effect'] = _codon_effect(
                        seq, genome_pos_0=genome_pos_0, cds_start_0=cds_start_0,
                        edited_base=ref_to)
                else:
                    entry['codon_effect'] = {
                        'status': 'not_applicable',
                        'reason': '本版本只支持 + 链 CDS 的密码子后果（cds_strand="-″ 需反向坐标支持）',
                    }
            else:
                entry['codon_effect'] = {
                    'status': 'not_applicable',
                    'reason': '未声明 cds_start_0：无法判断读码框，拒绝猜测（传 cds_start_0 后可算）',
                }
            editable.append(entry)
        if not editable:
            continue
        n_with_editable += 1
        window_positions = [e['protospacer_pos_1based'] for e in editable]
        warnings = []
        if len(editable) > 1:
            warnings.append(f'window 内有 {len(editable)} 个 {profile.substrate_base} '
                            f'（位置 {window_positions}）→ 会产生 bystander 混合产物，'
                            f'报告不能只写"实现了 {profile.substrate_base}→{profile.product_base}"')
        for e in editable:
            ce = e.get('codon_effect') or {}
            if ce.get('consequence') == 'nonsense':
                warnings.append(f'位置 {e["protospacer_pos_1based"]} 的编辑产生终止密码子'
                                f'（{ce.get("ref_codon")}→{ce.get("alt_codon")}）：'
                                f'敲除场景是目标，校正/点突变场景是风险')
        out.append({
            'protospacer': P,
            'pam': c.get('pam'),
            'guide_strand': g_strand,
            'start_0': c.get('start_0'),
            'end_0': c.get('end_0'),
            'nick_site_0': c.get('cut_site_0'),
            'nick_geometry': profile.nick_geometry,
            'template_hits': c.get('template_hits'),
            'editable_positions': editable,
            'n_editable_in_window': len(editable),
            'clean_single_edit': len(editable) == 1,
            'warnings': warnings,
        })

    out.sort(key=lambda x: (len(x['editable_positions']), x['start_0'] if x['start_0'] is not None else 0))
    returned = out[:int(top_n)]
    return {
        'editor': profile.name,
        'family': profile.family,
        'profile': profile.public_summary(),          # 五层结构原样带出，便于逐层引用
        'sequence_context': {'record_id': record_id, 'n_records': n_records,
                             'length_bp': len(seq)},
        'nuclease': nuclease.name,
        'strand_requested': strand,
        'window_used': {'start_1': win_lo, 'end_1': win_hi,
                        'counting': profile.window_counting,
                        'broader_window_included': bool(include_broader_window)},
        'n_candidates_scanned': len(candidates),
        'n_candidates_with_editable_base': n_with_editable,
        'n_returned': len(returned),
        'candidates': returned,
        'coordinate_system': COORDINATE_SYSTEM,
        'geometry_vs_efficiency': (
            '窗口内 = **几何兼容**；本工具**不预测**编辑效率/纯度。'
            '效率数据需实验测定或走 external provider（见 profile.applicability）。'),
        'boundary_semantics': ('窗口是经验观测范围、不是硬边界：窗口外低效不等于不编辑；'
                               '同一编辑器在不同靶点/细胞类型的窗口与活性都可能不同。'),
        'notes': [profile.notes] if profile.notes else [],
    }
