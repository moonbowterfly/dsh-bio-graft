"""editors.py — NucleaseProfile 编辑酶注册表（对象化，全局唯一事实源）。

设计原则：**编辑酶/碱基编辑器是一级对象**，不允许 `if cas9: ... elif cas12a: ...`
散落数十个函数。所有下游（guide 枚举、scoring、off-target、base-edit feasibility）
都从 profile 读语义。

2026-09-14 修正（唯一事实源）：PAM 表达式与 spacer 长度此前**双份维护**——
editors.py 有 pam_regex、guides.py 另有 `_SPACER_LEN` 与硬编码 PAM dict（改 profile
不生效）。现统一为 profile 的 `pam_pattern`（symbolic IUPAC）+ `spacer_length`。

证据分级：每个 profile 带 `verified` 与 `pam_source`。
  - verified=True  ：PAM/几何来自一手文献，可直接引用；
  - verified=False ：尚未对一手文献核对（或已知存疑），**下游必须如实转述**，
                     禁止把该 profile 的 PAM/切点当作既定事实写进报告。
"""
from __future__ import annotations


class NucleaseProfile:
    """编辑酶/编辑器配置对象 —— graft 的语义基石。"""

    def __init__(self, *, name, casual_name, pam_pattern, pam_side, spacer_length,
                 target_type, cut_offset, cut_structure, scoring_refs,
                 license_of_refs='public', verified=False, pam_source='', notes=''):
        self.name = name                      # 'SpCas9'
        self.casual_name = casual_name        # 'Cas9 (Sp, NGG)'
        self.pam_pattern = pam_pattern.upper()  # symbolic IUPAC：NGG / NG / NGN / TTTV / TNN / NNN
        self.pam_side = pam_side              # '3prime' | '5prime'
        self.spacer_length = spacer_length    # 唯一事实源（旧实现散在 guides._SPACER_LEN）
        self.target_type = target_type        # 'DNA' | 'RNA'
        self.cut_offset = cut_offset          # 3prime: PAM 起点上游 N bp；5prime: PAM 起点下游 N bp
        self.cut_structure = cut_structure    # 'blunt'|'staggered(1)'|'staggered(2)'|'nick'|'enzymatic-RNA'
        self.scoring_refs = scoring_refs      # 引用列表，不实现综合分
        self.license_of_refs = license_of_refs
        self.verified = verified              # PAM/几何是否已对一手文献核对
        self.pam_source = pam_source          # 引用（作者-年份-期刊 + 一句定位）
        self.notes = notes

    def public_summary(self):
        return {
            'name': self.name,
            'casual_name': self.casual_name,
            'pam': self.pam_pattern,
            'pam_side': self.pam_side,
            'spacer_length': self.spacer_length,
            'target_type': self.target_type,
            'cut_offset': self.cut_offset,
            'cut_structure': self.cut_structure,
            'verified': self.verified,
            'pam_source': self.pam_source,
            'scoring_refs': self.scoring_refs,
            'license_of_refs': self.license_of_refs,
            'notes': self.notes,
        }


# 内置注册表（v0.1 覆盖主流 nuclease；BaseEditorProfile 由 base_editors.py 另设）
EDITORS: dict[str, NucleaseProfile] = {}


def _register(p: NucleaseProfile):
    EDITORS[p.name] = p


_register(NucleaseProfile(
    name='SpCas9', casual_name='Cas9 (Sp, NGG)',
    pam_pattern='NGG', pam_side='3prime', spacer_length=20,
    target_type='DNA', cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 (Rule Set 2)', 'Chen-2013 (Hsu-Lab)'],
    license_of_refs='public-lit', verified=True,
    pam_source='Jinek 2012 Science 337:816 (SpCas9 需 NGG PAM)；切点为 PAM 上游 3 bp 平末端',
    notes='主流金标准；sgRNA 与靶链互补。',
))
_register(NucleaseProfile(
    name='SpCas9-NG', casual_name='Cas9-NG (NG)',
    pam_pattern='NG', pam_side='3prime', spacer_length=20,
    target_type='DNA', cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 (approx, use with caution)'],
    verified=True,
    pam_source='Nishimasu 2018 Science 361:1259（SpCas9-NG，NG PAM）',
    notes='PAM 放松版；脱靶风险更高，须加密 off-target QA。',
))
_register(NucleaseProfile(
    name='SpG', casual_name='SpG (NGN)',
    pam_pattern='NGN', pam_side='3prime', spacer_length=20,
    target_type='DNA', cut_offset=3, cut_structure='blunt',
    scoring_refs=['Doench-2016 approx (calibrate!)'],
    verified=True,
    pam_source='Walton 2020 Science 368:290（SpG：NGN PAM；SpRY 才近乎 PAM-less）',
    notes='SpCas9 变体，PAM 放松 NGN；使用须配更严格脱靶阈值。',
))
_register(NucleaseProfile(
    name='Cas12a', casual_name='Cpf1 (TTTV, 5prime PAM)',
    pam_pattern='TTTV', pam_side='5prime', spacer_length=20,
    target_type='DNA', cut_offset=18, cut_structure='staggered',
    scoring_refs=['crisprVerse rule-set (MIT impl 参考不引入)'],
    verified=True,
    pam_source='Zetsche 2015 Cell 163:759（LbCpf1/Cas12a：TTTV PAM，PAM 在 5\' 端，'
               'PAM 下游错口切割）',
    notes='5\' PAM；错口切割，适合定向敲入。cut_offset=18 为「PAM 起点下游 18 nt」的'
          '工程口径（staggered 双切点的代表值），报告须带 cut_structure=staggered。',
))
_register(NucleaseProfile(
    name='Cas12b', casual_name='Cas12b (TNN/TTN — 待核)',
    pam_pattern='TTN', pam_side='5prime', spacer_length=20,
    target_type='DNA', cut_offset=17, cut_structure='staggered',
    scoring_refs=['literature-default'],
    verified=False,
    pam_source='待核：本机原始声明为 TNN，与作者记忆中的 AapCas12b「TTN」不一致；'
               '核对一手文献（Shmakov 2015 / Teng 2018 / Strecker 2019）后再置 verified=True',
    notes='PAM 与几何**未核对**——报告里必须标明未验证，不得当作既定事实。',
))
_register(NucleaseProfile(
    name='Cas13a', casual_name='Cas13a (RNA targeting)',
    pam_pattern='NNN', pam_side='3prime', spacer_length=22,
    target_type='RNA', cut_offset=15, cut_structure='enzymatic-RNA',
    scoring_refs=['Cas13 design guidelines (Abudayyeh 2016)'],
    verified=False,
    pam_source='待核：Cas13a 为 RNA 靶向，无 DNA PAM 概念（使用 PFS/侧翼位点偏好）；'
               '当前 NNN 是占位声明',
    notes='RNA 靶向（不编辑基因组），P2 modality；目前只提供基本 profile，不做 deep designer。',
))


def get_editor(name: str) -> NucleaseProfile:
    e = EDITORS.get(name)
    if e is None:
        # 语义错误用 ValueError：KeyError 会被 graft_ops 的「缺参数」处理器误报成
        # "missing required arg"，把 agent 引向错误的排查方向（实测）。
        raise ValueError(f'unknown editor {name!r}; available: {sorted(EDITORS)}')
    return e


def profiles_summary() -> list[dict]:
    """给 graft_profiles 工具与 integration status 用的静态摘要（不 spawn Python）。"""
    return [e.public_summary() for e in EDITORS.values()]
