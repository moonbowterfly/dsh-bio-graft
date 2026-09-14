"""offtarget_interpret.py — 把 Cas-OFFinder 原始命中翻译成 **CRISPR 语义记录**（批次 C）。

设计原则（graft 铁律的工程化，GPT 裁决 #1/#2/#7/#9 定稿）：
  ① `search_completeness`：**枚举**本次搜索覆盖了哪些维度、哪些**没搜**（bulge/结构变异/
     样本变异）。「没搜」和「搜了没命中」科学意义完全不同——这是最容易被误读成「安全」的地方。
  ② `assessment.safety_conclusion` 恒为 `not_supported`：API 里**不存在** `safe: true`，
     也不存在裸 `risk_level`。工具只给 observation（观察值），结论由 agent 按证据撰写。
  ③ 负证据语义：`0` / `not_searched` 必须区分。
  ④ per-guide 汇总只是**事实分栏**（mismatch 数分布 / seed 区命中 / 最近位点），不是风险评分。
"""
from __future__ import annotations

SEARCH_COMPLETENESS_NOTE = (
    '本表枚举**本次搜索覆盖了什么**。`not_searched` 表示该维度**根本没有被这次搜索覆盖**——'
    '不得据此推断「无风险」；`searched` 只表示该维度在声明的参数下被搜索过。'
)

SAFETY_CONCLUSION = 'not_supported'
SAFETY_REASON = ('计算性序列搜索无法建立生物学安全性：它只能回答「在给定的参考序列与搜索参数下'
                 '发现了哪些序列相似位点」。安全性/风险结论需要实验验证、群体遗传学数据'
                 '与功能注释，超出本工具的证据范围。')

SEED_NOTE = ('seed 窗口按 PAM-proximal 端算（3′ PAM：匹配序列的末 seed_length 位；'
             '5′ PAM：前 seed_length 位）。不同文献的 seed 定义（8–12 nt）不一致，'
             '本工具只报**事实计数**，不声称与任一活性模型等效。')


def build_search_completeness(*, mismatch_searched: bool = True, dna_bulge: bool = False,
                              rna_bulge: bool = False, structural_variation: bool = False,
                              sample_variants: bool = False,
                              annotation: bool = False) -> dict:
    """枚举搜索覆盖度（searched / not_searched）。"""
    flag = lambda v: 'searched' if v else 'not_searched'  # noqa: E731
    return {
        'mismatch': flag(mismatch_searched),
        'dna_bulge': flag(dna_bulge),
        'rna_bulge': flag(rna_bulge),
        'structural_variation': flag(structural_variation),
        'sample_variants': flag(sample_variants),
        'functional_annotation': flag(annotation),
        'note': SEARCH_COMPLETENESS_NOTE,
    }


def build_assessment() -> dict:
    """反幻觉：工具层永不输出 safety/risk 结论。"""
    return {
        'safety_conclusion': SAFETY_CONCLUSION,
        'reason': SAFETY_REASON,
        'allowed_phrasing': '「在当前搜索参数下未检出高分位点」/「检出了以下位点」',
        'forbidden_phrasing': ['安全', '无脱靶', '无风险', 'safe', 'no off-target'],
    }


def _seed_window(length: int, seed_length: int, pam_side: str) -> tuple[int, int]:
    """返回 seed 窗口的 1-based 闭区间（按匹配序列自身坐标系）。"""
    if seed_length <= 0 or length <= 0:
        return (1, 0)
    if pam_side == '3prime':
        return (max(1, length - seed_length + 1), length)
    return (1, min(seed_length, length))


def aggregate_per_guide(hits: list, queries: list, *, seed_length: int = 8,
                        pam_side: str = '3prime') -> list[dict]:
    """按 query 汇总命中：数量 / mismatch 分布 / seed 区命中 / 最近位点。"""
    by_query: dict[str, list] = {q: [] for q in queries}
    for h in hits:
        by_query.setdefault(h.get('query'), []).append(h)

    out = []
    for q in queries:
        qhits = by_query.get(q, [])
        dist: dict[str, int] = {}
        seed_hits = 0
        for h in qhits:
            mm = str(h.get('mismatches'))
            dist[mm] = dist.get(mm, 0) + 1
            matched = h.get('matched_sequence') or ''
            lo, hi = _seed_window(len(matched), seed_length, pam_side)
            if any(lo <= p <= hi for p in (h.get('mismatch_positions_1based') or [])):
                seed_hits += 1
        nearest = None
        if qhits:
            best = min(qhits, key=lambda h: (h.get('mismatches', 99),
                                             h.get('position_0based', 10**12)))
            nearest = {
                'chromosome': best.get('chromosome'),
                'position_0based': best.get('position_0based'),
                'position_1based': best.get('position_1based'),
                'mismatches': best.get('mismatches'),
                'strand': best.get('strand'),
            }
        out.append({
            'query': q,
            'n_hits': len(qhits),
            'hits_by_mismatch': dict(sorted(dist.items(), key=lambda kv: int(kv[0]))),
            'seed_region_hits': seed_hits,
            'seed_window': _seed_window(len(q), seed_length, pam_side),
            'seed_note': SEED_NOTE,
            'exact_match_present': any(h.get('mismatches') == 0 for h in qhits),
            'nearest_site': nearest,
        })
    return out
