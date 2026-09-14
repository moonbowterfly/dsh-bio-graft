"""rank.py — 声明式候选排名（graft_rank）。

═══════════════════════════════════════════════════════════════════════════
设计契约（2026-09-14 GPT 裁决 #3/#13/#17 定稿）
═══════════════════════════════════════════════════════════════════════════
1. **秩是 policy-dependent 的序数表达**：返回体自带 policy_id + policy_digest，
   策略整体写进 EditPlan run，回答「为什么昨天 B 今天 D」。
2. **默认不做隐式加权**：policy='weighted' 必须显式给 weights，否则响亮报错。
   即使给了，返回的是 `declared_objective_value`（按声明权重、原始单位的线性组合）
   并附 disclaimer —— 绝不叫 "score"，绝不出现"综合质量分"这种伪精确。
3. **负证据语义**：过滤器/目标函数依赖的数据缺失（未做过该分析）时，
   必须**排除并写明 not_searched/missing**，绝不静默通过（"没有报错" ≠ "做过分析"）。
4. 三种 operator：
   - hard_filters   硬约束（模板内多位点/GC 区间/自回文/同聚物/脱靶命中数…）
   - lexicographic  字典序（用户声明"哪个criterion 更重要"）
   - pareto         支配关系（不引入价值偏好时唯一客观的表达）
   - weighted       仅显式权重，且带 disclaimer
"""
from __future__ import annotations

import hashlib
import json

# ── 度量注册表：name -> (extractor, direction) ────────────────────────────────
# direction: 'min' 表示越小越好；'max' 表示越大越好。extractor 返回 None = 该数据未做过。

def _scores(c: dict) -> dict:
    return (c.get('on_target_scores') or {}) if isinstance(c, dict) else {}


def _offtarget(c: dict) -> dict:
    return (c.get('offtarget_summary') or {}) if isinstance(c, dict) else {}


def _gc(c: dict):
    v = _scores(c).get('gc_content', c.get('gc_content') if isinstance(c, dict) else None)
    return None if v is None else float(v)


def _homopolymer_max(c: dict):
    runs = _scores(c).get('homopolymer_runs')
    if runs is None:
        return None
    return max((len(r) for r in runs), default=0)


def _offtarget_mm(c: dict, k: int):
    mm = _offtarget(c).get('hits_by_mismatch')
    if not isinstance(mm, dict):
        return None
    return mm.get(str(k), mm.get(k))


METRICS = {
    'template_hits': (lambda c: c.get('template_hits') if isinstance(c, dict) else None, 'min'),
    'gc_content': (_gc, 'min'),
    'gc_abs_dev': (lambda c: (None if _gc(c) is None else round(abs(_gc(c) - 0.5), 6)), 'min'),
    'max_self_palindrome': (lambda c: _scores(c).get('max_self_palindrome',
                                                     c.get('max_self_palindrome') if isinstance(c, dict) else None), 'min'),
    'homopolymer_max': (_homopolymer_max, 'min'),
    'cut_site_0': (lambda c: c.get('cut_site_0') if isinstance(c, dict) else None, 'min'),
    'offtarget_total': (lambda c: _offtarget(c).get('total'), 'min'),
    'offtarget_mm0': (lambda c: _offtarget_mm(c, 0), 'min'),
    'offtarget_mm1': (lambda c: _offtarget_mm(c, 1), 'min'),
    'offtarget_mm2': (lambda c: _offtarget_mm(c, 2), 'min'),
    'offtarget_mm3': (lambda c: _offtarget_mm(c, 3), 'min'),
}

RANK_SEMANTICS = (
    '秩是 **policy-dependent** 的序数表达：同一组候选在不同策略下可以有不同的名次，'
    '因此返回值必须连 policy_id/policy_digest 一起引用。本工具**不产生**综合分/质量分。'
)

WEIGHTED_DISCLAIMER = (
    'declared_objective_value = 按**你声明的权重**对原始单位度量做的线性组合（未归一化），'
    '不是验证模型、不是活性/安全性预测；仅供在同一 policy 内比较，'
    '**不得**作为报告或方案的设计结论引用。换一组权重即换一个答案——这正是它必须随 '
    'policy 一起落账本的原因。'
)


def _parse_spec(spec: str) -> tuple[str, str]:
    """'template_hits:min' -> ('template_hits', 'min')；未知度量响亮报错。"""
    if not isinstance(spec, str) or ':' not in spec:
        raise ValueError(f'metric spec 必须形如 "name:min|max"，收到 {spec!r}')
    name, _, direction = spec.partition(':')
    name = name.strip()
    direction = (direction or 'min').strip().lower()
    if name not in METRICS:
        raise ValueError(f'unknown metric {name!r}；可用：{sorted(METRICS)}')
    if direction not in ('min', 'max'):
        raise ValueError(f'metric direction 必须是 min 或 max，收到 {direction!r}')
    return name, direction


def _policy_digest(policy_payload: dict) -> str:
    canon = json.dumps(policy_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(canon.encode('utf-8')).hexdigest()[:32]


def _filter_candidate(c: dict, hard_filters: dict | None) -> list[str]:
    """返回不合格原因列表（空 = 通过）。数据缺失按 not_searched 处理 → 不合格且有说明。"""
    reasons: list[str] = []
    if not hard_filters:
        return reasons
    for key, limit in hard_filters.items():
        if key == 'exclude_warnings':
            warnings = c.get('warnings') or []
            for needle in limit or []:
                if any(needle in w for w in warnings):
                    reasons.append(f'warning matched filter {needle!r}: {warnings}')
            continue
        if key.endswith('_max') or key.endswith('_min'):
            metric, op = key.rsplit('_', 1)
            if metric not in METRICS:
                raise ValueError(f'unknown hard filter {key!r}（没有度量 {metric!r}）')
            value = METRICS[metric][0](c)
            if value is None:
                reasons.append(f'{metric}=not_searched/missing data —— 无法评估该约束'
                               f'（负证据语义：缺失 ≠ 通过）')
                continue
            if op == 'max' and value > limit:
                reasons.append(f'{metric}={value} > max {limit}')
            if op == 'min' and value < limit:
                reasons.append(f'{metric}={value} < min {limit}')
            continue
        raise ValueError(f'unsupported hard filter {key!r}')
    return reasons


def rank_candidates(candidates: list, policy: str = 'pareto', order: list | None = None,
                    objectives: list | None = None, weights: dict | None = None,
                    hard_filters: dict | None = None, top_n: int | None = None) -> dict:
    """按声明式策略给候选排名。返回 ranked / excluded / pareto_front / policy 载荷。"""
    if not isinstance(candidates, list) or not candidates:
        raise ValueError('candidates required（来自 graft_design 的输出）')
    candidates = [c for c in candidates if isinstance(c, dict)]
    if not candidates:
        raise ValueError('candidates 里没有对象形态的候选')

    ranked_input: list[dict] = []
    excluded: list[dict] = []
    for c in candidates:
        reasons = _filter_candidate(c, hard_filters)
        label = c.get('protospacer') or c.get('guide') or '(unnamed)'
        if reasons:
            excluded.append({'protospacer': label, 'reasons': reasons})
        else:
            ranked_input.append(c)

    def vector(c: dict, keys: list[str]) -> dict:
        return {k: METRICS[k][0](c) for k in keys}

    entries: list[dict] = []
    pareto_front: list[str] = []

    if policy == 'lexicographic':
        specs = order or []
        if not specs:
            raise ValueError('lexicographic 需要 order=[...]（如 ["template_hits:min", ...]）')
        parsed = [_parse_spec(s) for s in specs]
        keys = [p[0] for p in parsed]

        def sort_key(c: dict):
            # 缺失值排最后（避免"没做过的分析"被当成最优）
            return tuple((1, 0) if METRICS[k][0](c) is None else (0, METRICS[k][0](c) * d)
                         for k, d in [(k, 1 if dd == 'min' else -1) for k, dd in parsed])

        ordered = sorted(ranked_input, key=sort_key)
        for i, c in enumerate(ordered, 1):
            entries.append({'rank': i, 'protospacer': c.get('protospacer'), 'vector_values': vector(c, keys)})
        policy_payload = {'policy': 'lexicographic', 'order': specs, 'hard_filters': hard_filters or {}}

    elif policy == 'pareto':
        specs = objectives or (order or ['template_hits:min', 'max_self_palindrome:min', 'gc_abs_dev:min'])
        parsed = [_parse_spec(s) for s in specs]
        keys = [p[0] for p in parsed]

        def dominates(a: dict, b: dict) -> bool:
            better = False
            for (k, d) in parsed:
                va, vb = METRICS[k][0](a), METRICS[k][0](b)
                if va is None or vb is None:
                    continue  # 该轴不可比（未做过该分析）——不据此宣称支配
                if d == 'min':
                    if va > vb:
                        return False
                    if va < vb:
                        better = True
                else:
                    if va < vb:
                        return False
                    if va > vb:
                        better = True
            return better

        dom_map = {}
        for c in ranked_input:
            doms = [o.get('protospacer') for o in ranked_input if o is not c and dominates(o, c)]
            dom_map[c.get('protospacer')] = doms
        front = [c.get('protospacer') for c in ranked_input if not dom_map.get(c.get('protospacer'))]
        pareto_front = front
        # 排序：先前沿，再按支配者数量少→多
        ordered = sorted(ranked_input,
                         key=lambda c: (0 if c.get('protospacer') in front else 1,
                                        len(dom_map.get(c.get('protospacer')) or [])))
        for i, c in enumerate(ordered, 1):
            name = c.get('protospacer')
            doms = dom_map.get(name) or []
            entries.append({
                'rank': i, 'protospacer': name, 'vector_values': vector(c, keys),
                'pareto_rank': 1 if name in front else 1 + min(len(doms), 1),
                'dominated_by': doms,
            })
        policy_payload = {'policy': 'pareto', 'objectives': specs, 'hard_filters': hard_filters or {}}

    elif policy == 'weighted':
        if not weights:
            raise ValueError('weighted 必须显式给 weights（本工具**不做默认隐形加权**）')
        for k in weights:
            if k not in METRICS:
                raise ValueError(f'unknown metric {k!r} in weights；可用：{sorted(METRICS)}')
        keys = sorted(weights)

        def wvalue(c: dict):
            total, missing = 0.0, []
            for k, w in weights.items():
                v = METRICS[k][0](c)
                if v is None:
                    missing.append(k)
                    continue
                total += float(w) * float(v)
            return round(total, 6), missing

        enriched = [(c, *wvalue(c)) for c in ranked_input]
        enriched.sort(key=lambda t: t[1])
        for i, (c, val, missing) in enumerate(enriched, 1):
            entry = {'rank': i, 'protospacer': c.get('protospacer'),
                     'vector_values': vector(c, keys),
                     'declared_objective_value': val}
            if missing:
                entry['missing_metrics'] = missing
                entry['missing_note'] = ('这些度量缺数据（not_searched），已按"不计入"处理；'
                                         '若它们重要，先跑对应分析再排名')
            entries.append(entry)
        policy_payload = {'policy': 'weighted', 'weights': weights, 'hard_filters': hard_filters or {}}

    else:
        raise ValueError(f'unknown policy {policy!r}；可用：pareto / lexicographic / weighted')

    if top_n is not None and top_n > 0:
        entries = entries[:int(top_n)]

    return {
        'policy': policy_payload,
        'policy_id': f"{policy_payload['policy']}:"
                     + ','.join(map(str, policy_payload.get('order') or policy_payload.get('objectives')
                                    or list((policy_payload.get('weights') or {}).items()))),
        'policy_digest': _policy_digest(policy_payload),
        'n_input': len(candidates),
        'n_ranked': len(entries),
        'n_excluded': len(excluded),
        'ranked': entries,
        'excluded': excluded,
        'pareto_front': pareto_front,
        'rank_semantics': RANK_SEMANTICS,
        'disclaimer': WEIGHTED_DISCLAIMER if policy == 'weighted' else RANK_SEMANTICS,
        'note': ('rank 表达的是"在声明策略下 A 优于 B"；换策略可以换名次——'
                 '把 policy 一起写进 EditPlan run（graft_plan_save 的 ranking_policy 字段）。'),
    }
