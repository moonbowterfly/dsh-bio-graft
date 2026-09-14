# 编辑器几何证据债（PROFILES-TODO）

> 规则：`NucleaseProfile.verified=false` 的编辑器，其 **PAM 模式 / spacer 长度 / 切点几何**
> 尚未对**一手文献**核对。在核实之前：
> ① 报告里必须标注「PAM/几何未验证」；
> ② 不得用其 cut_site 做下游决策（如 HDR 供体设计）；
> ③ 不得在工具 description / skill 里把它写成事实。
>
> 核对完成后：改 `python/editors.py` 里该 profile 的 `verified`/`pam_source`，
> 并在此文件划掉对应行（保留历史）。

| 编辑器 | 当前声明 | 状态 | 待核要点 |
|---|---|---|---|
| SpCas9 | PAM `NGG`，3′，spacer 20，blunt，cut = PAM 起点 −3 | ✅ verified（Jinek 2012 / Cong 2013） | — |
| SpCas9-NG | PAM `NG`，3′，spacer 20，blunt，cut −3 | ✅ verified（Nishimasu 2018） | 活性随 PAM 变化大，scoring_refs 已标 approx |
| SpG | PAM `NGN`，3′，spacer 20，blunt，cut −3 | ✅ verified（Walton 2020） | 与 SpRY（近 PAM-less）区分表述 |
| Cas12a | PAM `TTTV`，5′，spacer 20，staggered，cut = PAM 起点 +18 | ✅ verified（Zetsche 2015） | staggered 的**双切点**（如 18/23）口径：本工具只报主切点，报告须带 `cut_structure=staggered` |
| **Cas12b** | PAM **`TTN`**，5′，spacer 20，staggered，cut +17 | ❌ **未核** | ① 本机原始声明是 `TNN`，与 `TTN` 不一致——哪个对？核对 AapCas12b 一手文献（Shmakov 2015 / Teng 2018 / Strecker 2019）；② spacer 长度与切点偏移；③ 是否存在 editing-window 差异 |
| **Cas13a** | 占位 `NNN`，3′，spacer 22，enzymatic-RNA | ❌ **未核** | Cas13a 靶 RNA、无 DNA PAM 概念（用 PFS/侧翼偏好）；当前为占位声明，designer 未实现（调 `graft_design` 会被明确拒绝） |

## 还需补的外部事实（非 profile 本体）

- **Cas-OFFinder 版本与设备行为**：v2.4.1 已实测（三段式 input、0-based 输出、CPU OpenCL 缺失时的行为）。
  若上游发布新版本，重跑 `test/offtarget-scan.mjs` 的夹具确认契约未变。
- **bulge 搜索**：Cas-OFFinder 本体不支持，官方用包装脚本 `cas-offinder-bulge`（独立项目）。
  当前 graft 对 bulge 请求响亮报错；若将来要支持，需重新评估其许可与维护状态后再接入（作为 external adapter）。
