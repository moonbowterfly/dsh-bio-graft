"""guides.py — sgRNA 候选枚举 + on-target 评分向量。

设计原则（GPT 评审裁决采纳，核心）：
- 保留 **score vector（评分向量）**，绝不生成"87.3 综合分"——那会制造伪精确
- rank 由 plan_create / agent 按 objective function 完成

v0.1 简化（诚实范围）：PAM 表达式用**显式字符串匹配**（'NGG' 逐位对比，N=任意），
不走 regex——Cas-OFFinder 原生格式同样按此语义；Sp/SpG/SpCas9-NG/Cas12a/Cas12b
都能覆盖。Cas13a RNA 靶向 v0.1 只列 profile 不做 designer（见 editors.py）。
"""
from __future__ import annotations

import re

_REVCOMP_TABLE = str.maketrans('ACGTNacgtn', 'TGCANtgcan')


def revcomp(seq: str) -> str:
    return seq.translate(_REVCOMP_TABLE)[::-1]


def _gc(seq: str) -> float:
    if not seq:
        return 0.0
    return (seq.upper().count('G') + seq.upper().count('C')) / len(seq)


def _homopolymers(seq: str, min_run: int = 4) -> list[str]:
    runs = []
    i = 0
    s = seq.upper()
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        if j - i >= min_run:
            runs.append(s[i:j])
        i = j
    return runs


def _max_self_palindrome(seq: str, min_len: int = 4) -> int:
    s = seq.upper()
    best = 0
    for L in range(min_len, len(s) + 1):
        for i in range(len(s) - L + 1):
            chunk = s[i:i + L]
            if chunk == revcomp(chunk):
                best = max(best, L)
    return best


def _pam_match(pam_pattern: str, seq: str, at: int) -> int | None:
    """在 seqat 位置尝试 PAM 逐位匹配（N=通配）。返回 PAM 实际长度 or None。"""
    s = seq.upper()
    p = pam_pattern.upper()
    if at + len(p) > len(s):
        return None
    for i, c in enumerate(p):
        if c == 'N':
            continue
        if s[at + i] != c:
            return None
    return len(p)


_SPACER_LEN = {'SpCas9': 20, 'SpCas9-NG': 20, 'SpG': 20, 'Cas12a': 20, 'Cas12b': 20, 'Cas13a': 22}


def enumerate_guides(sequence: str, editor: str = 'SpCas9',
                     position_base: str = '1', top_n: int = 100,
                     scan_both_strands: bool = True) -> dict:
    """扫序列枚举 sgRNA（symbolic PAM 匹配，支持双向）。"""
    if not sequence or not sequence.strip():
        raise ValueError('sequence required (raw DNA or FASTA)')
    seq0 = ''.join(sequence.split())
    if seq0.startswith('>'):
        seq0 = re.sub(r'^>[^\n]*\n?', '', seq0, count=1)
    seq = seq0.upper()
    if not seq:
        raise ValueError('empty sequence after cleaning')
    profile = get_editor(editor)
    L = _SPACER_LEN.get(profile.name, 20)
    pam_pat = profile.pam_regex.pattern.replace('(?=', '').replace(')', '')
    if profile.name == 'SpCas9':
        # editors.py 里写了 '(?=.{21}NGG)'——取后半 NGG
        pam_pat = profile.pam_regex.pattern.split('}', 1)[-1].rstrip(')').replace('(?=', '').replace(')', '')
        pam_pat = 'NGG' if not pam_pat else pam_pat.strip('()N=').replace('N', 'N') or 'NGG'
        pam_pat = 'NGG'
    # 统一重申（安全）
    pam_pat = {'SpCas9': 'NGG', 'SpCas9-NG': 'NG', 'SpG': 'NGN',
               'Cas12a': 'TTTV', 'Cas12b': 'TNN', 'Cas13a': 'NNN'}.get(profile.name, pam_pat)
    pam_len = len(pam_pat)

    def scan_plus(s: str, strand: str):
        out = []
        if profile.pam_side == '3prime':
            for i in range(0, len(s) - L - pam_len + 1):
                pl = _pam_match(pam_pat, s, i + L)
                if pl is None:
                    continue
                out.append({'protospacer': s[i:i + L], 'pam': s[i + L:i + L + pl],
                            'start_0': i, 'end_0': i + L + pl,
                            'strand': strand})
        else:  # 5prime (Cas12a/b)
            for i in range(0, len(s) - L - pam_len + 1):
                pl = _pam_match(pam_pat, s, i)
                if pl is None:
                    continue
                spacer = s[i + pl:i + pl + L]
                out.append({'protospacer': spacer, 'pam': s[i:i + pl],
                            'start_0': i, 'end_0': i + pl + L,
                            'strand': strand})
        return out

    candidates = scan_plus(seq, '+')
    if scan_both_strands:
        rev = revcomp(seq)
        rc = scan_plus(rev, '-')
        # 反向链候选映射回原链坐标：rev pos p ↔ orig pos len-1-p
        mapped = []
        n_orig = len(seq)
        for c in rc:
            rs, re_ = c['start_0'], c['end_0']
            # 该候选在 rev 上占据 [rs, re_)
            orig_start = n_orig - re_
            orig_end = n_orig - rs
            mapped.append({**c, 'start_0': orig_start, 'end_0': orig_end})
        candidates += mapped

    candidates.sort(key=lambda c: (c['start_0'], c['strand']))
    # 模板内重复计数（多位点匹配检测）——一个 guide 匹配多处 = 多位点切割，
    # 敲除/敲入实验不可用。实测（2026-09-12 E2E）：高重复序列里 27 条候选
    # 只有 10 条唯一 protospacer、仅 5 条合格——agent 曾手工做这个统计，
    # 现在是工具内置事实（每个候选带 template_hits + multi_match warning）。
    from collections import Counter
    spacer_counter = Counter(c['protospacer'] for c in candidates)
    for c in candidates:
        hits = spacer_counter.get(c['protospacer'], 1)
        c['template_hits'] = hits
        if hits > 1:
            c.setdefault('warnings', []).append(
                f'multi_match: protospacer 在模板中出现 {hits} 次（多位点切割风险，'
                f'敲除类实验通常需剔除）')
    n_unique = len(spacer_counter)
    candidates = candidates[:top_n]
    return {
        'editor': editor,
        'pam_pattern': pam_pat,
        'spacer_length': L,
        'position_base': str(position_base),
        'n_candidates_raw': len(candidates),
        'n_unique_protospacers': n_unique,
        'multi_match_note': (f'{len(candidates)} 条候选对应 {n_unique} 条唯一 protospacer；'
                             f'template_hits>1 的候选有多位点切割风险' if n_unique < len(candidates) else None),
        'candidates': candidates,
        'note': 'start_0/end_0 = 0-based 半开区间 [start, end)；strand 为 guide 对应的靶点在原链的方向',
    }


def score_guides(candidates: list, editor: str = 'SpCas9', **kwargs) -> dict:
    """给候选打 **on-target 评分向量**（无综合分）。"""
    profile = get_editor(editor)
    input_candidates = candidates or []
    if not isinstance(input_candidates, list) or not input_candidates:
        raise ValueError('candidates required (来自 guide_enumerate 的输出)')
    scored = []
    for i, c in enumerate(input_candidates):
        if isinstance(c, dict):
            spacer = (c.get('protospacer') or '').upper()
            pam = c.get('pam')
            start_0 = c.get('start_0')
            end_0 = c.get('end_0')
            strand = c.get('strand', '+')
        else:
            spacer = str(c).upper()
            pam = None
            start_0 = end_0 = None
            strand = '+'
        if not spacer:
            continue
        gc = _gc(spacer)
        runs = _homopolymers(spacer, 4)
        pal = _max_self_palindrome(spacer)
        u6 = spacer[0] == 'G'
        seed = spacer[-8:]
        warnings = []
        if len(spacer) not in (20, 21, 22):
            warnings.append(f'unusual spacer length {len(spacer)}')
        if gc < 0.20 or gc > 0.85:
            warnings.append('extreme GC (<0.20 or >0.85)')
        if runs:
            warnings.append(f'homopolymer {runs[0]}')
        if pal >= 8:
            warnings.append(f'self-palindrome {pal}nt (secondary structure risk)')
        scored.append({
            'idx': i,
            'protospacer': spacer,
            'pam': pam,
            'start_0': start_0,
            'end_0': end_0,
            'strand': strand,
            'on_target_scores': {
                'gc_content': round(gc, 4),
                'gc_class': 'low' if gc < 0.35 else ('high' if gc > 0.75 else 'mid'),
                'homopolymer_runs': runs,
                'max_self_palindrome': pal,
                'u6_start_pref': bool(u6),
                'seed_8nt_pam_proximal': seed,
            },
            'warnings': warnings,
        })
    return {
        'editor': editor,
        'n_scored': len(scored),
        'candidates': scored,
        'score_semantics': ('score vector only — 不产生综合分；'
                            'rank 由 plan_create / agent 按 objective 完成'),
    }


from editors import get_editor  # noqa: E402  (循环导入安全：editors.py 无反向依赖)
