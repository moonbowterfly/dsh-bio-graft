"""base_editors.py — BaseEditorProfile 注册表（碱基编辑器，五层结构）。

═══════════════════════════════════════════════════════════════════════════
设计契约（2026-09-14 GPT 裁决 #5/#9 定稿，务必遵守）
═══════════════════════════════════════════════════════════════════════════
1. **五层结构**：targeting / chemistry / activity / evidence / applicability。
   每一层都可独立引用，禁把不同层的主张混成一句。
2. **geometry 与 efficiency 彻底拆开**：
   目标碱基落在窗口内 → 只能推出「几何兼容（geometrically compatible）」，
   **不能**推出「会高效编辑」。因此本文件里**没有** 任何效率/活性预测字段；
   `applicability.efficiency_model_available` 明确标记「本插件未内置预测模型」。
3. **窗口编号约定（必须随数字一起传播）**：
   位置 1 = protospacer 的 **PAM-distal** 端；PAM 记为位置 21–23（20 nt spacer + NGG）。
   依据：Gaudelli 2017 Nature 551:464 原文「from protospacer positions ~4–7 for ABE7.10
   … counting the PAM as positions 21–23」；BE3 的 4–8 同约定（Komor 2016 Nature 533:420，
   约定见 Liu-lab 综述 PMC6535181）。
4. **证据分级**：每个 profile 带 `verified` + `window_evidence`（含文献与计数约定）。
   窗口核不到一手来源的编辑器**不入注册表**（宁可少支持，不可编数字）。
5. ML 预测（BE-Hive / inDelphi / DeepBE 等非商业许可）一律走 external provider，**永不 bundle**。
"""
from __future__ import annotations

WINDOW_COUNTING = ('位置 1 = protospacer 的 PAM-distal 端；PAM 记为位置 21–23'
                   '（20 nt spacer + NGG）。依据 Gaudelli 2017 原文计数约定。')

EFFICIENCY_GAP = ('本插件未内置活性/效率预测模型：窗口内只推「几何兼容」，不推「会高效编辑」。'
                  '预测层（BE-Hive / inDelphi / DeepBE 等，多为非商业或学术专用许可）'
                  '一律走 external provider，不随本插件分发。')


class BaseEditorProfile:
    """碱基编辑器配置对象（五层结构）。"""

    def __init__(self, *, name, casual_name, family,
                 # ── L1 targeting ──────────────────────────────────────────
                 nuclease, pam_pattern, pam_side, spacer_length, nick_geometry,
                 # ── L2 chemistry ──────────────────────────────────────────
                 substrate_base, product_base, edited_strand_semantics,
                 # ── L3 activity（几何事实，不是活性预测）──────────────────
                 core_window, broader_observed_window, window_counting=WINDOW_COUNTING,
                 # ── L4 evidence ───────────────────────────────────────────
                 refs, verified, evidence_level, window_evidence,
                 # ── L5 applicability ──────────────────────────────────────
                 efficiency_model_available=False, extrapolation_warning=EFFICIENCY_GAP,
                 notes=''):
        # L1 targeting
        self.nuclease = nuclease
        self.pam_pattern = pam_pattern.upper()
        self.pam_side = pam_side
        self.spacer_length = spacer_length
        self.nick_geometry = nick_geometry
        # L2 chemistry
        self.substrate_base = substrate_base.upper()
        self.product_base = product_base.upper()
        self.edited_strand_semantics = edited_strand_semantics
        # L3 activity
        self.core_window = tuple(core_window) if core_window else None
        self.broader_observed_window = tuple(broader_observed_window) if broader_observed_window else None
        self.window_counting = window_counting
        # L4 evidence
        self.refs = refs
        self.verified = verified
        self.evidence_level = evidence_level
        self.window_evidence = window_evidence
        # L5 applicability
        self.efficiency_model_available = efficiency_model_available
        self.extrapolation_warning = extrapolation_warning
        self.name = name
        self.casual_name = casual_name
        self.family = family
        self.notes = notes

    def public_summary(self) -> dict:
        return {
            'name': self.name,
            'casual_name': self.casual_name,
            'family': self.family,
            'targeting': {
                'nuclease': self.nuclease,
                'pam': self.pam_pattern,
                'pam_side': self.pam_side,
                'spacer_length': self.spacer_length,
                'nick_geometry': self.nick_geometry,
            },
            'chemistry': {
                'substrate_base': self.substrate_base,
                'product_base': self.product_base,
                'edited_strand_semantics': self.edited_strand_semantics,
            },
            'activity': {
                'core_window': list(self.core_window) if self.core_window else None,
                'broader_observed_window': (list(self.broader_observed_window)
                                            if self.broader_observed_window else None),
                'window_counting': self.window_counting,
                'boundary_semantics': 'not_absolute — 窗口是经验观测范围，不是硬边界；'
                                      '窗口外低效不等于不编辑',
            },
            'evidence': {
                'refs': self.refs,
                'verified': self.verified,
                'evidence_level': self.evidence_level,
                'window_evidence': self.window_evidence,
            },
            'applicability': {
                'efficiency_model_available': self.efficiency_model_available,
                'extrapolation_warning': self.extrapolation_warning,
            },
            'notes': self.notes,
        }


BASE_EDITORS: dict[str, BaseEditorProfile] = {}


def _register(p: BaseEditorProfile) -> None:
    BASE_EDITORS[p.name] = p


_register(BaseEditorProfile(
    name='BE3', casual_name='BE3 (rAPOBEC1-nCas9(D10A)-UGI)', family='CBE',
    nuclease='SpCas9', pam_pattern='NGG', pam_side='3prime', spacer_length=20,
    nick_geometry='nCas9 D10A 缺口在 PAM 上游 3 bp（非编辑链）',
    substrate_base='C', product_base='T',
    edited_strand_semantics='编辑发生在与 protospacer 互补的那条链上的 C（即 protospacer 上的 C）',
    core_window=(4, 8), broader_observed_window=(2, 8),
    refs=['Komor 2016 Nature 533:420 (BE3 原始报道)',
          'Rees & Liu 2018 Nat Rev Mol Cell Biol（窗口与计数约定综述）'],
    verified=True, evidence_level='primary-literature',
    window_evidence='窗口 4–8，PAM 记为位置 21–23。来源：Komor 2016 Nature 533:420（BE3 原始报道，'
                    'rAPOBEC1 + nCas9(D10A) + UGI）；计数约定原文见 Liu-lab 综述 PMC6535181'
                    '（"positions 4–8, counting the PAM as positions 21–23"）。',
    notes='第一代 CBE；窗口内多个 C 会产生 bystander 混合产物。',
))

_register(BaseEditorProfile(
    name='BE4max', casual_name='BE4max (codon-optimized BE4)', family='CBE',
    nuclease='SpCas9', pam_pattern='NGG', pam_side='3prime', spacer_length=20,
    nick_geometry='nCas9 D10A 缺口在 PAM 上游 3 bp（非编辑链）',
    substrate_base='C', product_base='T',
    edited_strand_semantics='同 BE3 家族',
    core_window=(4, 8), broader_observed_window=(2, 8),
    refs=['Koblan 2018 Nat Biotechnol 36:843 (BE4max)',
          'Arbab 2020 Cell (BE4 家族窗口测量：positions 4–8 ≥50% of max)'],
    verified=True, evidence_level='primary-literature + measured window',
    window_evidence='窗口 4–8（BE4 家族实测口径「≥50% of maximum frequency at positions 4–8」，'
                    'PMC7384975）；BE4max 为 BE4 的密码子优化+NLS 版本',
    notes='窗口沿用 BE4 家族实测值；各靶点实际窗口仍有差异（window 非硬边界）。',
))

_register(BaseEditorProfile(
    name='ABE7.10', casual_name='ABE7.10 (TadA-TadA*-nCas9)', family='ABE',
    nuclease='SpCas9', pam_pattern='NGG', pam_side='3prime', spacer_length=20,
    nick_geometry='nCas9 D10A 缺口在 PAM 上游 3 bp（非编辑链）',
    substrate_base='A', product_base='G',
    edited_strand_semantics='编辑发生在 protospacer 上的 A（经脱氨→肌苷→读作 G）',
    core_window=(4, 7), broader_observed_window=(3, 9),
    refs=['Gaudelli 2017 Nature 551:464 (ABE7.10)'],
    verified=True, evidence_level='primary-literature',
    window_evidence='原文：activity windows「approximately 4–6 nucleotides wide, from '
                    'protospacer positions ~4–7 for ABE7.10」，且明示 counting the PAM as '
                    'positions 21–23（PMC5726555）。broader_observed 4–9 对应同期 ABE6.3/7.8/7.9，'
                    '此处仅作参考范围标注',
    notes='A→G（A•T→G•C）；窗口边缘（3/4/7/8）活性差异大——见 ABE8 系进化论文。',
))


def get_base_editor(name: str) -> BaseEditorProfile:
    p = BASE_EDITORS.get(name)
    if p is None:
        raise ValueError(f'unknown base editor {name!r}; available: {sorted(BASE_EDITORS)}'
                         f'（未核一手窗口的编辑器不入注册表；见 docs/PROFILES-TODO.md）')
    return p


def base_editors_summary() -> list[dict]:
    return [p.public_summary() for p in BASE_EDITORS.values()]
