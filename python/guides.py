"""guides.py — sgRNA 候选枚举 + on-target 评分向量。

设计原则（核心）：
- 保留 **score vector（评分向量）**，绝不生成 "87.3 综合分"——那会制造伪精确；
  rank 由 graft_rank / plan_create 按声明的 objective 完成。
- 所有几何（PAM 表达式 / spacer 长度 / 切点偏移）**只从 NucleaseProfile 读**
  （2026-09-14 修正：此前 spacer 长度与 PAM 在本文件另存一份，改 profile 不生效）。

PAM 匹配语义：**IUPAC 感知**（N=ACGT、V=ACG、R=AG、Y=CT …）。
历史缺陷：旧实现只认 'N'，于是 Cas12a 的 'TTTV' 里的 V 被当字面量 → 恒返回 0 候选。

坐标口径（全部写进返回值，供 agent 引用，见 `coordinate_system`）：
- `start_0`/`end_0`：0-based 半开区间 [start, end)，**含 PAM**；
- `start_1`/`end_1`：1-based 闭区间等价表示；
- `cut_site_0`：0-based，切点位于 `cut_site_0-1` 与 `cut_site_0` 两位之间；
- `cut_site_verified=False`：该编辑器的几何尚未对一手文献核对，禁止当作既定事实。
"""
from __future__ import annotations

from collections import Counter

from editors import get_editor
from sequtil import clean_sequence, gc_content, revcomp

# IUPAC 展开表（PAM 与 pattern 共用）
_IUPAC = {
    'A': 'A', 'C': 'C', 'G': 'G', 'T': 'T',
    'R': 'AG', 'Y': 'CT', 'S': 'CG', 'W': 'AT', 'K': 'GT', 'M': 'AC',
    'B': 'CGT', 'D': 'AGT', 'H': 'ACT', 'V': 'ACG', 'N': 'ACGT',
}

COORDINATE_SYSTEM = (
    'start_0/end_0 = 0-based 半开区间 [start, end)，含 PAM；start_1/end_1 = 1-based 闭区间；'
    'cut_site_0 = 0-based，切点位于 cut_site_0-1 与 cut_site_0 两碱基之间，'
    'cut_site_1based = cut_site_0 + 1；cut_site_verified=False 表示该几何尚未核对一手文献'
)


def pam_match(pam_pattern: str, seq: str, at: int) -> int | None:
    """在 seq 的 at 位置按 IUPAC 语义匹配 PAM，返回匹配到的 PAM 长度或 None。

    未知符号一律**响亮失败**——PAM 定义错误不应该静默变成「没有候选」。
    """
    s = seq.upper()
    p = pam_pattern.upper()
    if at < 0 or at + len(p) > len(s):
        return None
    for i, code in enumerate(p):
        allowed = _IUPAC.get(code)
        if allowed is None:
            raise ValueError(f'unknown IUPAC code {code!r} in PAM pattern {pam_pattern!r}')
        if s[at + i] not in allowed:
            return None
    return len(p)


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
    """最长完美自回文长度（近似二级结构风险指标；不建模带环的发夹）。"""
    s = seq.upper()
    best = 0
    for L in range(min_len, len(s) + 1):
        for i in range(len(s) - L + 1):
            chunk = s[i:i + L]
            if chunk == revcomp(chunk):
                best = max(best, L)
    return best


def cut_site_for(profile, *, pam_start_0: int) -> tuple[int, str, bool]:
    """按 profile 声明的几何算 DSB 位点，返回 (cut_site_0, convention, verified)。

    口径（显式声明，供 agent 与报告引用）：
      3prime PAM（SpCas9 系）：cut_site_0 = PAM 起点 − cut_offset
        例 SpCas9 cut_offset=3 → 平末端切点在 PAM 起点上游 3 bp。
      5prime PAM（Cas12a/Cas12b）：cut_site_0 = PAM 起点 + cut_offset
        例 Cas12a cut_offset=18 → 切点在 PAM 起点下游 18 nt（错口，staggered）。
    """
    if profile.pam_side == '3prime':
        site = pam_start_0 - profile.cut_offset
        conv = (f'{profile.name}: cut_site_0 = PAM 起点 − {profile.cut_offset} '
                f'({profile.cut_structure})')
    else:
        site = pam_start_0 + profile.cut_offset
        conv = (f'{profile.name}: cut_site_0 = PAM 起点 + {profile.cut_offset} '
                f'({profile.cut_structure}，主切点)')
    return site, conv, bool(profile.verified)


def enumerate_guides(sequence: str, editor: str = 'SpCas9',
                     position_base: str = '1', top_n: int = 100,
                     scan_both_strands: bool = True, record: int = 0) -> dict:
    """扫描序列枚举 sgRNA 候选（symbolic PAM 匹配，IUPAC 感知，可选双向）。"""
    seq, record_id, n_records = clean_sequence(sequence, record=record)
    profile = get_editor(editor)
    if profile.target_type != 'DNA':
        raise ValueError(
            f'{profile.name} 靶向 {profile.target_type}，v0.1 不提供 designer；'
            f'请用 DNA 靶向编辑器（如 SpCas9/Cas12a）')
    L = profile.spacer_length
    pam_pat = profile.pam_pattern
    pam_len = len(pam_pat)

    def scan_plus(s: str, strand: str):
        out = []
        if profile.pam_side == '3prime':
            for i in range(0, len(s) - L - pam_len + 1):
                pl = pam_match(pam_pat, s, i + L)
                if pl is None:
                    continue
                site_rc, conv, verified = cut_site_for(profile, pam_start_0=i + L)
                out.append({'protospacer': s[i:i + L], 'pam': s[i + L:i + L + pl],
                            'start_0': i, 'end_0': i + L + pl, 'strand': strand,
                            '_cut_site_frame': site_rc, '_cut_convention': conv,
                            '_cut_verified': verified})
        else:  # 5prime（Cas12a/Cas12b）
            for i in range(0, len(s) - L - pam_len + 1):
                pl = pam_match(pam_pat, s, i)
                if pl is None:
                    continue
                site_rc, conv, verified = cut_site_for(profile, pam_start_0=i)
                out.append({'protospacer': s[i + pl:i + pl + L], 'pam': s[i:i + pl],
                            'start_0': i, 'end_0': i + pl + L, 'strand': strand,
                            '_cut_site_frame': site_rc, '_cut_convention': conv,
                            '_cut_verified': verified})
        return out

    candidates = scan_plus(seq, '+')
    n_orig = len(seq)
    if scan_both_strands:
        rc = scan_plus(revcomp(seq), '-')
        # 反向链候选映射回原链坐标：rev 上的区间 [rs, re_) ↔ orig 上的 [n-re_, n-rs)
        # 点位（切点）同理：rev 上的 k ↔ orig 上的 n - k
        for c in rc:
            rs, re_ = c['start_0'], c['end_0']
            c['start_0'] = n_orig - re_
            c['end_0'] = n_orig - rs
            c['_cut_site_frame'] = n_orig - c['_cut_site_frame']
            candidates += [c]
        candidates = [c for c in candidates]
    candidates.sort(key=lambda c: (c['start_0'], c['strand']))

    # 模板内重复计数（多位点匹配检测）——一个 guide 匹配多处 = 多位点切割，敲除类不可用。
    spacer_counter = Counter(c['protospacer'] for c in candidates)
    for c in candidates:
        hits = spacer_counter.get(c['protospacer'], 1)
        c['template_hits'] = hits
        warnings = []
        if hits > 1:
            warnings.append(
                f'multi_match: protospacer 在模板中出现 {hits} 次（多位点切割风险，'
                f'敲除类实验通常需剔除）')
        cut_site_0 = c.pop('_cut_site_frame')
        conv = c.pop('_cut_convention')
        verified = c.pop('_cut_verified')
        if cut_site_0 < 0:
            warnings.append(f'cut_site_0={cut_site_0} 落在序列起点之外（PAM 贴边），'
                            f'该位点实际不可用')
        c['cut_site_0'] = cut_site_0
        c['cut_site_1based'] = cut_site_0 + 1
        c['cut_site_convention'] = conv
        c['cut_site_verified'] = verified
        c['start_1'] = c['start_0'] + 1
        c['end_1'] = c['end_0']
        if warnings:
            c['warnings'] = warnings

    n_raw = len(candidates)
    n_unique = len(spacer_counter)
    returned = candidates[:top_n]
    return {
        'editor': profile.name,
        'pam_pattern': pam_pat,
        'pam_side': profile.pam_side,
        'spacer_length': L,
        'record_id': record_id,
        'n_records': n_records,
        'n_records_note': (f'输入是多条 FASTA，仅使用第 {record + 1} 条 (record_id={record_id})；'
                           f'需要其他条请传 record=N' if n_records > 1 else None),
        'position_base': str(position_base),
        'coordinate_system': COORDINATE_SYSTEM,
        'n_candidates_raw': n_raw,
        'n_returned': len(returned),
        'n_unique_protospacers': n_unique,
        'multi_match_note': (f'{n_raw} 条候选对应 {n_unique} 条唯一 protospacer；'
                             f'template_hits>1 的候选有多位点切割风险'
                             if n_unique < n_raw else None),
        'candidates': returned,
        'note': ('start_0/end_0 = 0-based 半开区间 [start, end) 含 PAM；'
                 'strand 为 guide 对应的靶点在原链的方向；'
                 'cut_site_verified=False 的编辑器几何未核对一手文献'),
    }


def score_guides(candidates: list, editor: str = 'SpCas9', **kwargs) -> dict:
    """给候选打 **on-target 评分向量**（无综合分）。"""
    profile = get_editor(editor)
    input_candidates = candidates or []
    if not isinstance(input_candidates, list) or not input_candidates:
        raise ValueError('candidates required（来自 guide_enumerate 的输出）')
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
        gc = gc_content(spacer)
        runs = _homopolymers(spacer, 4)
        pal = _max_self_palindrome(spacer)
        u6 = spacer[0] == 'G'
        seed = spacer[-8:]
        warnings = []
        if len(spacer) not in (profile.spacer_length, profile.spacer_length + 1):
            warnings.append(f'unusual spacer length {len(spacer)} '
                            f'(expected {profile.spacer_length} for {profile.name})')
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
            'start_1': (start_0 + 1) if isinstance(start_0, int) else None,
            'end_1': end_0,
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
        'editor': profile.name,
        'n_scored': len(scored),
        'candidates': scored,
        'score_semantics': ('score vector only — 不产生综合分；'
                            'rank 由 graft_rank / plan_create 按声明的 objective 完成'),
    }
