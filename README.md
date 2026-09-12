# dsh-bio-graft

> 基因编辑设计专科插件（dsh-bio-genie 生态的 g 系成员）
> **Gene-editing design specialty plugin for [dsh](https://github.com/deepseek-ai/deepseek-harness)**

**graft**（嫁接）——把设计好的序列变更「接入」既有基因组。与 `dsh-bio-genie`（许愿式分析宿主）
和 `dsh-bio-gem`（代谢模型专科）构成 g 系产品家族：

| 插件 | 隐喻 | 职责 |
|---|---|---|
| **genie** | 许愿| 通用生信宿主：49+ 语义化工具 + 自举 Python 环境 + 出版级绘图 |
| **gem** | 晶石（模型资产） | 基因组尺度代谢模型：构建/验证/补洞/账本 |
| **graft** | 嫁接（序列变更） | 基因编辑设计：sgRNA 候选 / 评分向量 / 脱靶扫描 / EditPlan 账本 |

## 核心哲学

**desired edit first, tool second** —— 用户描述「要什么编辑」，graft 先比选
modality（nuclease / base editing / prime editing / HDR / paired deletion），
而不是先让用户选工具。

**Score vector，不是综合分** —— 每个 sgRNA 候选保留完整评分向量
（GC / 同聚物 / 自回文 / U6 起始偏好 / seed 序列），**不打「87.3 分」这种
伪精确综合分**；最终推荐由 agent 按 objective 结合证据解释。

**EditPlan 是可审计科学对象** —— 每次设计迭代不是「重新聊天」，而是
修改/追加一个 `.editplan.json`（append-only `runs/` 账本）。可回答
「为什么昨天推荐 B、今天推荐 D？」（因为 reference / backend / ranking policy 变了）。

**脱靶铁律** —— No computational off-target method may label a design as safe.
只可说「在当前搜索参数下未检出高分位点」。

## v0.1 能力（7 个语义化工具）

| 工具 | 说明 |
|---|---|
| `graft_profiles` | 内置 NucleaseProfile 注册表（SpCas9 / SpCas9-NG / SpG / Cas12a / Cas12b / Cas13a） |
| `graft_design` | PAM 双向扫描枚举 sgRNA 候选 + 评分向量（含坐标体系与 strand） |
| `graft_score` | 对已有候选列表单独打评分向量 |
| `graft_offtarget` | Cas-OFFinder（BSD-3 官方 Windows 二进制）批量脱靶扫描 |
| `graft_backend_status` | 后端探测 / `action=ensure` 自动安装 Cas-OFFinder |
| `graft_plan_save` | EditPlan 写入（new / add_run / update_recommendation） |
| `graft_plan_load` | EditPlan 读回（主 plan + 全部 runs 时间线） |

## 安装（作为 dsh 插件）

```bash
dsh plugin add @dsh-bio/dsh-bio-graft --profile web
```

宿主 `dsh-bio-genie` 会通过 **hosted-domain integration 协议 v1**
（`/api/dsh-bio-graft/integration/health` 与 `/v1/status`）感知 graft 的安装与运行状态，
并在 BioGenie 设置面板提供条件子页。

## 运行依赖

| 依赖 | 说明 |
|---|---|
| Python ≥3.10 | 复用 `dsh-bio-genie` 自举环境（`GRAFT_PYTHON` 可显式指定解释器） |
| Cas-OFFinder（可选） | 官方 Windows x86-64 二进制，BSD-3。`graft_backend_status action=ensure` 自动下载到 `~/.dsh/dsh-bio-graft/bin/` |

## 数据目录

```
~/.dsh/dsh-bio-graft/
├── bin/cas-offinder.exe        # 自动安装的脱靶扫描后端
└── plans/
    ├── <name>.editplan.json     # 当前推荐 + 最新状态
    └── <name>/runs/             # append-only 账本（001_xxx.json, 002_xxx.json, …）
```

## 安全边界（架构级门控，写在 skill 中）

- **Level 0 科研常规**（非致病微生物/细胞系/模式生物）：正常提供设计
- **Level 1 人类 somatic 研究**：可设计 + 脱靶评估，但必须显式提示
  `research design ≠ clinical suitability`
- **Level 2 临床决策**：降级为 evidence/risk-analysis 模式
- **Level 3 germline/可遗传人类编辑、病原体增强**：不进入可执行序列设计

## 许可与第三方

本插件 MIT。**不 bundle 任何许可不兼容的第三方代码**：
- Cas-OFFinder（BSD-3）以**外部二进制**形式由用户机器托管（自动下载/手动放置），
  详见 `THIRD_PARTY_NOTICES.md`
- FlashFry（GPL-3+）/ PrimeDesign（AGPL+商业双许可）/ inDelphi（非商业）/
  CRISPResso2（非商业学术 EULA）→ 一律 **external adapter**，检测到用户合法安装时接入

## Roadmap

| 版本 | 内容 |
|---|---|
| v0.1（当前） | NucleaseProfile + sgRNA 枚举/评分 + Cas-OFFinder + EditPlan |
| v0.2 | BaseEditorProfile、可编辑窗口分析、bystander 枚举、paired-guide |
| v0.3 | Prime editing、CRISPRi/a、Cas13、HDR 供体设计、验证方案规划 |
| v0.4 | 编辑结果预测（provider 化）、CRISPResso2 适配、结果↔EditPlan 回灌闭环 |

## 架构

见 `docs/ARCHITECTURE.md`（编写中）。集成协议见 `src/integration.js`。

---

*Part of the **dsh-bio** plugin family · `@dsh-bio/dsh-bio-graft`*
