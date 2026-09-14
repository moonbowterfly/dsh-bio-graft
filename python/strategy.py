"""strategy.py — EditStrategy（多 guide 策略）几何评估（批次 E′）。

═══════════════════════════════════════════════════════════════════════════
为什么要有这一层（GPT 裁决 #6/#15/#16）
═══════════════════════════════════════════════════════════════════════════
多 guide 不能只是 `Guide[]`：**双 guide 的风险不是两个单 guide 风险的简单相加**。
- 几何层：两条 guide 的切点共同决定「删掉哪一段」→ 预测连接点（junction）、缺失长度、是否移码。
- 事件层：两条 guide 各自的脱靶位点**两两组合**可能产生额外缺失/易位（pairwise_event），
  不能只报 sum(offtarget(g1), offtarget(g2))。
- 证据层：本模块只做**几何与组合事实**；效率（缺失能否高效发生）不预测——
  文献里缺失效率与长度/位点强相关，本插件不内置该模型。

判定纪律：
  ① 只报可复算的几何事实（切点、区间、junction、长度、移码、PAM 朝向、overlap）；
  ② 未实现的策略（prime_edit / hdr / multiplex…）显式 `implemented: false`，**不许假装支持**；
  ③ pairwise 只在两条 guide 都带 offtarget 命中数据时才算；数据缺失报 `not_searched`（负证据语义）。
"""
from __future__ import annotations

STRATEGIES: dict[str, dict] = {
    'single_cut': {
        'implemented': True,
        'zh': '单切口（nuclease 敲除/敲入起点）',
        'requires': ['candidates'],
        'note': '单 guide 场景直接用 graft_design / graft_rank，不需本工具排策略。',
    },
    'deletion_pair': {
        'implemented': True,
        'zh': '双 guide 缺失（两条 guide 的切点夹住目标区段 → 释放该片段）',
        'requires': ['candidates'],
        'optional': ['region_start_0', 'region_end_0', 'cds_start_0'],
        'note': '切点由候选自带（cut_site_0）；本工具预测缺失区间与连接点。',
    },
    'paired_nickase': {
        'implemented': True,
        'zh': '配对切口酶（两条 nCas9 在相对链上各切一口，降低单切口带来的 indel）',
        'requires': ['candidates'],
        'optional': ['max_offset_bp'],
        'note': '只报几何配对的可行性事实（异链 + 间距），不预测特异性提升幅度。',
    },
    'multiplex_knockout': {
        'implemented': False,
        'zh': '多重敲除（多个独立靶点同时编辑）',
        'requires': ['多个靶区的候选集合'],
        'note': '需要跨靶区的候选分组语义（本版本未实现）——先用 graft_design 分别设计、'
                '各自 graft_rank，再在 EditPlan 里作为多条 run 记录。',
    },
    'base_edit': {
        'implemented': 'elsewhere',
        'zh': '碱基编辑',
        'note': '走 graft_base_edit（窗口几何 + bystander + 密码子后果）。',
    },
    'prime_edit': {
        'implemented': False,
        'zh': 'prime editing（pegRNA）',
        'note': '未实现——如实说明，不假装支持（pegRNA 设计需 PBS/RTT 设计与二级结构评估）。',
    },
    'hdr': {
        'implemented': False,
        'zh': 'HDR 供体设计',
        'note': '未实现——如实说明（供体臂长/同源臂设计需独立的证据与几何规则）。',
    },
}

PAIRWISE_NOTE = (
    'pairwise 分析只回答「两条 guide 的脱靶命中两两组合后，是否存在能共同产生缺失/易位的几何组合」，'
    '**不是**把两条 guide 的风险相加；也不是风险建模（那需要实验与群体数据）。'
)


def _cut_of(c: dict):
    return c.get('cut_site_0')


def _pair_geometry(a: dict, b: dict, *, cds_start_0: int | None = None) -> dict | None:
    """两条候选的几何关系 → 预测缺失区间/junction/移码。切点缺失时返回 None。"""
    ca, cb = _cut_of(a), _cut_of(b)
    if ca is None or cb is None:
        return None
    if ca > cb:
        a, b, ca, cb = b, a, cb, ca
    size = cb - ca
    return {
        'left': {'protospacer': a.get('protospacer'), 'strand': a.get('strand'),
                 'cut_site_0': ca, 'pam': a.get('pam')},
        'right': {'protospacer': b.get('protospacer'), 'strand': b.get('strand'),
                  'cut_site_0': cb, 'pam': b.get('pam')},
        'deleted_interval_0based_half_open': [ca, cb],
        'deleted_size_bp': size,
        'left_flank_end_0based': ca,
        'right_flank_start_0based': cb,
        'junction_rule': '预测连接点 = 左侧序列 [0, cut_left) 直接接右侧序列 [cut_right, len)',
        'protospacers_overlap': bool(
            a.get('start_0') is not None and b.get('start_0') is not None and
            min(a.get('end_0'), b.get('end_0')) > max(a.get('start_0'), b.get('start_0'))),
        'same_strand': a.get('strand') == b.get('strand'),
        'in_frame': (None if cds_start_0 is None else (size % 3 == 0)),
        'frameshift_note': ('缺失长度 %3 != 0 → 移码；%3 == 0 → 保持读码框（对敲除而言移码通常更彻底）'
                            if cds_start_0 is not None else
                            '未声明 cds_start_0：不判断移码（不猜读码框）'),
    }

def _pairwise_offtarget(a: dict, b: dict, *, window_bp: int = 10000, max_events: int = 20) -> dict:
    """两条 guide 的脱靶命中两两组合：同一染色体、间距在窗口内 → 可能共同造成缺失。"""
    ha = (a.get('offtarget_hits') or (a.get('offtarget_summary') or {}).get('hits') or [])
    hb = (b.get('offtarget_hits') or (b.get('offtarget_summary') or {}).get('hits') or [])
    if not ha or not hb:
        missing = []
        if not ha:
            missing.append('left.no_offtarget_hits')
        if not hb:
            missing.append('right.no_offtarget_hits')
        return {'status': 'not_searched', 'missing': missing,
                'note': '两条 guide 都需带 offtarget 命中数据（先跑 graft_offtarget 并把 hits 传进来）；'
                        '缺失即 not_searched，不得当「无风险」'}
    events = []
    for x in ha:
        for y in hb:
            if x.get('chromosome') != y.get('chromosome'):
                continue
            d = abs(int(y.get('position_0based', 0)) - int(x.get('position_0based', 0)))
            if d <= window_bp:
                events.append({
                    'chromosome': x.get('chromosome'),
                    'left_pos_0based': x.get('position_0based'),
                    'right_pos_0based': y.get('position_0based'),
                    'distance_bp': d,
                    'left_mismatches': x.get('mismatches'),
                    'right_mismatches': y.get('mismatches'),
                })
    events.sort(key=lambda e: e['distance_bp'])
    return {'status': 'computed', 'window_bp': window_bp,
            'n_pair_events': len(events), 'events': events[:max_events],
            'note': PAIRWISE_NOTE}


def evaluate_strategy(candidates: list, strategy: str = 'deletion_pair', *,
                      region_start_0: int | None = None, region_end_0: int | None = None,
                      cds_start_0: int | None = None, max_offset_bp: int = 200,
                      pairwise_window_bp: int = 10000, top_n: int = 20) -> dict:
    """评估一个 EditStrategy 的候选组合（几何 + 组合事实；不做效率预测）。"""
    meta = STRATEGIES.get(strategy)
    if meta is None:
        raise ValueError(f'unknown strategy {strategy!r}；可用：{sorted(STRATEGIES)}')
    if meta.get('implemented') is not True:
        return {
            'strategy': strategy, 'implemented': meta.get('implemented'),
            'implementation_state': ('elsewhere' if meta.get('implemented') == 'elsewhere' else 'not_implemented'),
            'zh': meta.get('zh'), 'note': meta.get('note'),
            'verdict': 'cannot_design',
            'honesty': '本插件未实现该策略——不会给出看似可行的假设计；'
                       '如需，请按节点说明改走已实现路径或外部工具。',
            'available_strategies': sorted(STRATEGIES),
        }
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError('candidates 至少两条（策略评估需要组合）')

    if strategy == 'single_cut':
        return {'strategy': strategy, 'implemented': True, 'verdict': 'use_design_tools',
                'note': meta['note'], 'n_candidates': len(candidates)}

    pairs = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            g = _pair_geometry(candidates[i], candidates[j], cds_start_0=cds_start_0)
            if g is None:
                continue
            pair = {'pair_id': f'p{len(pairs) + 1}', **g,
                    'offtarget_pairwise': _pairwise_offtarget(
                        candidates[i], candidates[j], window_bp=pairwise_window_bp)}
            if strategy == 'paired_nickase':
                if g['same_strand']:
                    continue
                if not (0 <= g['deleted_size_bp'] <= max_offset_bp):
                    continue
                pair['nickase_offset_bp'] = g['deleted_size_bp']
            elif strategy == 'deletion_pair':
                if region_start_0 is not None and region_end_0 is not None:
                    cl, cr = g['deleted_interval_0based_half_open']
                    # 「覆盖声明区段」= 两个切点**夹住**该区段（缺失区间 ⊇ 区段），
                    # 不是「切点落在区段内」（后者是子区间，反而删不掉区段两端）。
                    # 真实会话实测：旧判据写反，导致工具返回的全是不覆盖区段的组合，
                    # agent 独立枚举后发现「工具评估集 ⊄ 我的覆盖集」。
                    covers = (cl <= region_start_0 and cr >= region_end_0)
                    pair['covers_declared_region'] = covers
                    if covers:
                        pair['extra_deleted_bp_outside_region'] = ((region_start_0 - cl) +
                                                                   (cr - region_end_0))
                    else:
                        pair['reject_reason'] = (
                            f"切点区间 [{cl}, {cr}) 未夹住声明区段 "
                            f"[{region_start_0}, {region_end_0})：两端各需 cut_left ≤ 起点、"
                            f"cut_right ≥ 终点")
            pairs.append(pair)

    n_not_covering = 0
    if strategy == 'deletion_pair':
        n_not_covering = sum(1 for p in pairs if not p.get('covers_declared_region', True))
        pairs = [p for p in pairs if p.get('covers_declared_region', True)]
        # 排序：**区段外附带删除的碱基数越少越精确**（再按缺失长度小→大）
        pairs.sort(key=lambda p: (p.get('extra_deleted_bp_outside_region', 0),
                                  p['deleted_size_bp']))
    else:
        pairs.sort(key=lambda p: p.get('nickase_offset_bp', p['deleted_size_bp']))

    return {
        'strategy': strategy,
        'implemented': True,
        'zh': meta['zh'],
        'n_candidates': len(candidates),
        'n_pairs_evaluated': len(pairs),
        'n_pairs_rejected_not_covering': n_not_covering,
        'pairs': pairs[:int(top_n)],
        'pairs_truncated': len(pairs) > int(top_n),
        'geometry_only': ('本工具只给几何与组合事实：缺失长度/连接点/移码/PAM 朝向/两两脱靶组合。'
                          '缺失效率、配对切口酶的特异性提升幅度等属实验问题，不预测。'),
        'pairwise_rule': PAIRWISE_NOTE,
        'declared_region': ([region_start_0, region_end_0]
                            if region_start_0 is not None and region_end_0 is not None else None),
        'coordinate_note': '所有坐标均为参考序列 + 链的 0-based 半开区间；cut_site_0 来自候选自身。',
    }
