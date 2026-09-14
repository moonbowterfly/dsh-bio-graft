---
name: graft-expert
language: python
---

# 基因编辑设计（graft-expert，编辑生命周期总指引）

> dsh-bio-graft 的专科 skill。**核心哲学：desired edit first, tool second**——
> 用户描述要什么编辑，graft 生成的 EditIntent 先比选 modality（nuclease /
> base editing / prime editing / HDR / paired deletion），不要让用户先选工具。
>
> 宿主配套：dsh-bio-graft 是 dsh-bio-genie 的**能力域专科插件**（感知式组合）。
> 宿主 genie 保留通用 sequence primitives（IO/比对/primer 热力学/绘图），
> graft 独占编辑语义（编辑酶注册表/PAM 几何/guide 枚举/脱靶解释/候选排序/
> EditPlan 账本/验证方案）。

## 何时用

用户提到：设计 sgRNA、CRISPR knockout/knockin、碱基编辑、prime editing、
脱靶评估、HDR 供体、编辑验证方案、save 编辑计划。

## 编辑生命周期（TARGET → DESIGN → RANK → VERIFY → AUDIT）

```
TARGET    明确编辑目标（序列/坐标/物种/组装版本/编辑意图 desired_change）
DESIGN    graft_profiles 先看编辑酶 → graft_design 枚举候选 → graft_score 评分向量
RANK      用 **graft_rank** 按声明策略排名（pareto / lexicographic / 显式 weighted）——
          排序必须由工具完成并输出 policy_id + policy_digest，再用
          graft_plan_save(action=update_recommendation, ranking_policy=<policy 载荷>) 落账本；
          排序解释要保留证据：「B 的活性略高但 D 的脱靶更低，按本 objective 推荐 D」
VERIFY    graft_plan_save(action=add_run) 记录 validation_plan（引物/测序策略）
AUDIT     graft_plan_load 的 runs/ 时间线可回答「为什么昨天排名 B 今天 D」
```

## 工具清单

| 工具 | 说明 |
|---|---|
| `graft_profiles` | 列出内置 NucleaseProfile（PAM/geometry/scoring 文献引用） |
| `graft_design` | sgRNA 枚举 + 评分向量（不打综合分） |
| `graft_score` | 单独对候选列表打分（复用） |
| `graft_rank` | **声明式排名**（pareto / lexicographic / weighted-显式权重）；返回 policy_id + policy_digest + 被剔除原因；负证据语义（数据缺失=not_searched，绝不静默通过） |
| `graft_offtarget` | Cas-OFFinder 脱靶扫描（BSD-3，需用户准备 genome FASTA + 模式文件） |
| `graft_backend_status` | 后端探测/ensure 安装 Cas-OFFinder |
| `graft_plan_save` | EditPlan 写入（new/add_run/update_recommendation） |
| `graft_plan_load` | EditPlan 读回（plan + 全部 runs） |

## 硬规则（搭在 architecture 级 gate，不靠 agent 自觉）

0. **多位点检测是工具内置事实**：`graft_design` 的每个候选带 `template_hits`
   （protospacer 在模板内出现次数）与 `multi_match` 警告；**敲除类实验必须剔除
   `template_hits > 1` 的候选**（一个 guide 匹配多处 = 多位点切割，实验不可用）。
   报告里注明「X 条候选 → Y 条唯一 → Z 条合格」的口径。
1. **Off-target 永不说 safe**——「No computational off-target method may
   label a design as safe」。只能说「在当前搜索参数下未检出高分位点」
   / 「预测风险较低或较高」/「在 XX 组学文库功能注释里有 XX 提示」。
2. **保留评分向量，禁止综合分**——「87.3 分」是伪精确；**排名必须由 `graft_rank` 完成**并保留
   `policy_id`/`policy_digest`（策略随结果落账本）；agent 必须能解释「A 活性略高、B 脱靶更低，
   按本 objective 推荐 B」。`graft_rank` 的 `weighted` 模式**必须显式给权重**，其
   `declared_objective_value` 不得当作结论引用。
2b. **负证据语义**：`0` / `null` / `not_searched` / `not_applicable` 必须区分——
   「没做过该分析」绝不能表述成「结果为 0」或「无风险」。graft_rank 的硬过滤在数据缺失时
   会剔除并说明；agent 引用时也必须把缺失讲清楚。
3. **所有修改走 graft_plan_save 追加 run**，不覆盖——可审计。
4. **关键参数必须由工具输出，不要心算**——gc/坐标全部来自 graft_design。
5. **风险分级门控**（risk_context，写在 EditPlan.risk_flags）：
   - **Level 0 科研常规**（非致病微生物/细胞系/模式生物/基础研究）→ 正常提供设计
   - **Level 1 人类 somatic 研究** → 可做设计/比较/脱靶评估，但必须加
     `research_design ≠ clinical_suitability` 的显式提示（FDA 2024/2026 WHO guidance）
   - **Level 2 临床决策** → 不进入设计模式；降级为 evidence/risk-analysis mode
   - **Level 3 germline/可遗传人类编辑 / 病原体增强（毒性/传播/免疫逃逸/耐药）** →
     **不进入可执行序列设计**；可做文献讨论/伦理分析/风险比较、检测和防御分析
   - 判断依据来自 intent 的 organism / 疾病语境 / 意图声明；不确定时先向用户澄清
6. **permissive core + provider 化 + 不吞许可不兼容的源码**：本插件 bundle 的
   后端只有 Cas-OFFinder（BSD-3）；FlashFry (GPL-3)/PrimeDesign (非商业+商业双许可)/
   inDelphi (non-commercial)/CRISPResso2 (non-commercial academic EULA) 一律
   external adapter——检测到用户合法安装时接入，不配 bundled。

## MVP 边界 (v0.1)

- 已做：SpCas9 家族 PAM 扫描、评分向量、Cas-OFFinder 扫描、EditPlan ledger
- 未做（后续版本）：base editing 几何（v0.2）、prime editing（v0.3）、
  CRISPRi/a 与 Cas13 designer（v0.3）、HDR 供体设计（v0.3）、
  编辑结果预测（provider 化 v0.4）、CRISPResso2 集成（v0.4）

## 验收标准

- [ ] 每个 sgRNA 报告附带坐标体系（start_0/end_0 半开区间）和 strand
- [ ] 脱靶报告**不出现**「安全」/「无脱靶」字样
- [ ] 所有 EditPlan 修改都通过 graft_plan_save 落盘（不覆盖历史）
- [ ] 用户意图涉及 Level 2/3 时，明确降级并说明理由
- [ ] 报告里数字全部来自工具输出（genie 计算防火墙兜底）
