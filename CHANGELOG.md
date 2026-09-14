# Changelog

> 版本号规范：只递增 patch（0.0.1 步长）。
> **0.1.0 / 0.1.1 未发布到 npm**；`0.1.2` 是首个 npm 发布版本（内容涵盖前两版全部改动）。

## 0.1.2 (2026-09-15)

### 接入与工程（批次 A/B）
- **hosted-domain integration 协议 v2 载荷**：`health`（pluginId/pluginVersion/protocolMajor/protocolMinors/features）
  与 `status`（state/generatedAt/checks 数组/data/env/remediations）；宿主 genie 据此在设置面板托管
  「基因编辑设计」条件分页并做六态判定。
- **`capabilities.json`** 能力声明（`dsh-bio/capabilities@1`）：域 id / 工具前缀 / 中英触发词 / 集成端点 /
  必检项 / 资产权威源 / 重叠规则 / 外部二进制 / 安全铁律。
- **版本单一事实源**（`src/version.js` 读 package.json），消除硬编码漂移。
- **测试网 `npm test` = 145 断言**（工具/op 契约、黄金 op、真实 Cas-OFFinder 夹具、排名夹具、
  碱基编辑夹具、integration 契约；`GRAFT_STRICT=1` 严格模式禁止静默跳过）。
- 文档：`docs/ARCHITECTURE.md`、`docs/PROFILES-TODO.md`（编辑器几何/窗口的证据债清单）、
  `docs/decisions/`（设计裁决记录）、`docs/PLAN-2026-09-14.md`（施工计划）。

### 新工具与能力（批次 C/D）
- **`graft_rank`**：声明式排名 —— `pareto` / `lexicographic` / `weighted`（**须显式给权重**）；
  返回 `policy_id` + `policy_digest`（策略随结果进 EditPlan）；硬过滤被剔除的候选带原因；
  **负证据语义**：依赖数据缺失（没做过该分析）时剔除并写明 `not_searched`，绝不静默通过。
- **`graft_base_edit`**：碱基编辑设计（CBE/ABE）—— 窗口内可编辑碱基 + **bystander** + 密码子后果
  （synonymous/missense/nonsense/stop_loss）；内置 BE3 / BE4max / ABE7.10（窗口均经一手文献核对，
  带计数约定与出处）；**链语义三件套**（反链 guide 的 C→T 在参考正链上表现为 G→A）；
  **只做几何、不预测活性**（`efficiency_model_available=false`）。
- **`graft_offtarget` 语义层**：`search_completeness`（**枚举没搜的维度**：bulge/结构变异/样本变异）、
  `assessment`（`safety_conclusion` 恒为 `not_supported`；API 里不存在 `safe:true`）、
  `per_guide`（mismatch 分布 / seed 区命中 / 最近位点）；`preflight_only` 基因组体检；`device=auto`。
- `graft_design` 候选新增 **切割位点**（`cut_site_0` + `cut_site_convention` + `cut_site_verified`）。

### 修复（批次 A + E2E 回流）
- **Cas-OFFinder 调用契约**：三段式 input 文件（genome 路径 / pattern / query+mismatch）、
  `exe <input> {C|G|A} <out>`、无表头 6 列 0-based 解析 —— 此前脱靶扫描**从未真正可用**。
- **FASTA 输入解析**：旧实现先拼接再正则，贪婪头行吃掉整条序列 → 任何 FASTA 输入必失败。
- **IUPAC 感知 PAM 匹配**：旧实现只认 `N`，`TTTV` 里的 `V` 被当字面量 → **Cas12a 恒返回 0 候选**（且不报警）。
- **桥接编码契约**：`stdin/stdout/stderr` 全部 UTF-8 —— 此前 agent 传中文参数必炸
  （`UnicodeEncodeError: surrogates not allowed`）。
- **工具工厂**：不再覆盖自定义 `execute` —— 此前分支型工具（`graft_backend_status`）恒报 `unknown op: None`。
- **EditPlan 账本**：run 号单调只增（旧实现删 run 后撞号 = 重写审计历史）、原子写、同名默认拒绝覆盖、
  记录所有传入字段、支持 `plan_name` 解析、缺 `reference.sequence_hash` 给提醒。
- **排名可用性**：脱靶摘要兼容嵌套/扁平两种形态；未知 filter/metric 报错列出可用名。

### 证据与纪律（产品级）
- 编辑器几何带 `verified` / `pam_source`；未核一手文献的（Cas12b/Cas13a）如实标注，禁止当既定事实。
- 脱靶**永不说安全**：结构化 `assessment` + 0 命中给 `zero_hit_warning` + 参数随结论走。
- 「高效」不给裸词：只报评分向量 + 声明式策略；效率预测一律 external provider。

## 0.1.0 / 0.1.1 (2026-09-12 → 09-14)

- 0.1.0：初始骨架 —— NucleaseProfile 注册表、PAM 双向枚举、评分向量（不打综合分）、
  Cas-OFFinder 驱动、EditPlan（.editplan.json + append-only runs 账本）、风险分级门控。
- 0.1.1：批次 A「可信底座」—— 修 9 个缺陷 + 建立测试网 + GitHub 仓库与 tag v0.1.1。
