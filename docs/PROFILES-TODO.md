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

## 待评估（不是缺陷，是版本边界与外部事实）

- **Cas-OFFinder 版本边界（2026-09-14 本机核验）**：GitHub releases 上 `2.4.1`（2021-01-23）是**最后一个稳定版**，
  之后有 `3.0.0b` / `3.0.0b2` / `3.0.0b3`（beta，2021-07-29）。当前插件钉在 2.4.1（稳定 + 已实测通过）。
  - 3.0.0b3 的 Windows 资产命名是 `cas-offinder_windows_x86_64.zip`（**下划线**），而 2.4.1 是
    `cas-offinder_windows_x86-64.zip`（**连字符**）——若将来加「指定版本安装」参数，URL 模板必须分别处理。
  - 3.0.0b3 的 release **无 release notes**（本机 API 核验），无法确认「3.0.0 原生支持 bulge」这一说法；
    master README 的 changelog 止于 2.3，且明确写 bulge 需独立包装脚本 `cas-offinder-bulge`。
    **在证实之前不改代码**（外部模型提出、本机无法证实的断言一律只入待评估清单）。
  - 无论版本如何，**v2.4.1 的「未检出」不可推出「无 bulge 脱靶」**——现状已用「bulge 请求响亮报错 +
    `search_parameters.bulge: unsupported` + 边界声明」实现该纪律；批次 C 会再加 `search_completeness` 枚举字段。
- **契约回归**：若上游发布新版本并被采用，必须重跑 `test/offtarget-scan.mjs` 夹具确认三段式 input /
  0-based 输出 / 设备语义未变。
- **Cas-OFFinder 设备**：本机无 CPU OpenCL 设备（`C` 直接失败），只能 GPU（`device=auto` 已自动处理）。
  若将来支持 Linux/macOS 打包，device 语义需重新实测（Linux 常见有 CPU OpenCL runtime）。
