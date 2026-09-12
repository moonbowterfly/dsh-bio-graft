"""editors.py — NucleaseProfile 编辑酶注册表（对象化，全局唯一事实源）。

设计原则（GPT 评审裁决采纳）：**编辑酶/碱基编辑器是一级对象**，不允许
`if cas9: ... elif cas12a: ...` 散落数十个函数。所有下游（guide 枚举、
scoring、off-target、base-edit feasibility）都从 profile 读语义。

NucleaseProfile 携带：
  PAM grammar（正则 + PAM 位置 5'/3'）
  target type（DNA/RNA）
  strand semantics（sgRNA 与靶链的关系）
  cut/edit geometry（blunt/stagger、offset）
  supported scoring models（引用，不在本插件实现"综合分"）
  version / references
"""
from __future__ import annotations

import re


class NucleaseProfile:
    """编辑酶/编辑器配置对象 —— graft 的语义基石。"""

    def __init__(self, *, name, casual_name, pam_regex, pam_side, target_type,
                 cut_offset, cut_structure, scoring_refs, license_of_refs='public',
                 notes=''):
        self.name = name                      # 'SpCas9'
        self.casual_name = casual_name        # 'Cas9 (NGG)'
        self.pam_regex = re.compile(pam_regex, re.I)
        self.pam_side = pam_side              # '3prime'|'5prime'
        self.target_type = target_type        # 'DNA'|'RNA'
        self.cut_offset = cut_offset          # 相对 PAM 的切点（blunt=3）
        self.cut_structure = cut_structure    # 'blunt'|'staggered(1)|(n)'|'nick'|'deamination'
        self.scoring_refs = scoring_refs      # 引用列表，不实现
        self.license_of_refs = license_of_refs
        self.notes = notes

    def public_summary(self):
        return {
            'name': self.name,
            'casual_name': self.casual_name,
            'pam': self.pam_regex.pattern.upper(),
            'pam_side': self.pam_side,
            'target_type': self.target_type,
            'cut_offset': self.cut_offset,
            'cut_structure': self.cut_structure,
            'scoring_refs': self.scoring_refs,
            'license_of_refs': self.license_of_refs,
            'notes': self.notes,
        }


# 内置注册表（v0.1 先覆盖主流 4 类；碱基编辑器/Prime editor 由 BaseEditorProfile 在 v0.2 扩展）
EDITORS: dict[str, NucleaseProfile] = {}


def _register(p: NucleaseProfile):
    EDITORS[p.name] = p


_register(NucleaseProfile(
    name='SpCas9', casual_name='Cas9 (Sp, NGG)',
    pam_regex=r'(?=.{21}NGG)',  # 由 guides.py 展开具体扫描；此处仅描述
    pam_side='3prime', target_type='DNA',
    cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 (Rule Set 2)', 'Chen-2013 (Hsu-Lab)', 'CRISPOR composite (ref only)'],
    license_of_refs='public-lit',
    notes='主流金标准； Watson-Crick 靶标，sgRNA 与靶链互补。',
))
_register(NucleaseProfile(
    name='SpCas9-NG', casual_name='Cas9-NG (NG)',
    pam_regex=r'(?=.{21}NG)', pam_side='3prime', target_type='DNA',
    cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 (approx, use with caution)'],
    notes='PAM 放松版；脱靶风险更高，须加密 off-target QA。',
))
_register(NucleaseProfile(
    name='Cas12a', casual_name='Cpf1 (TTTV, 5prime PAM)',
    pam_regex=r'(?=TTTV.{20})', pam_side='5prime', target_type='DNA',
    cut_offset=18, cut_structure='staggered(1)',
    scoring_refs=['crisprVerse rule-set (MIT impl 参考不引入)'],
    notes='5prime PAM；错口切割，适合定向敲入。',
))
_register(NucleaseProfile(
    name='Cas12b', casual_name='Cas12b (TNN)',
    pam_regex=r'(?=TNN.{19})', pam_side='5prime', target_type='DNA',
    cut_offset=17, cut_structure='staggered(2)',
    scoring_refs=['literature-default'],
))
_register(NucleaseProfile(
    name='Cas13a', casual_name='Cas13a (RNA targeting)',
    pam_regex=r'(?=NNN.{21})', pam_side='3prime', target_type='RNA',
    cut_offset=15, cut_structure='enzymatic-RNA',
    scoring_refs=['Cas13 design guidelines (Abudayyeh 2016)'],
    notes='RNA 靶向（不编辑基因组），P2 modality；v0.1 提供基本 profile，不做 deep designer。',
))
_register(NucleaseProfile(
    name='SpG', casual_name='SpG (NGN)',
    pam_regex=r'(?=.{21}NGN)', pam_side='3prime', target_type='DNA',
    cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 approx (calibrate!)'],
    notes='SpCas9 变体，PAM 放松 NGN；使用须配更严格脱靶阈值。',
))


def get_editor(name: str) -> NucleaseProfile:
    e = EDITORS.get(name)
    if e is None:
        raise KeyError(f'unknown editor {name!r}; available: {sorted(EDITORS)}')
    return e
