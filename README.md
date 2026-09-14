# dsh-bio-graft

<div align="center">

**中文** | [English](README.en.md)

</div>

> 基因编辑设计专科插件（dsh-bio-genie 生态的 g 系成员）
> **Gene-editing design specialty plugin for [dsh](https://github.com/deepseek-ai/deepseek-harness)**
> `dsh bio crispr` · `dsh 基因编辑设计` · `dsh-bio plugin` · `deepseek harness bioinformatics`

**graft**（嫁接）——把设计好的序列变更「接入」既有基因组。与 `dsh-bio-genie`（许愿式分析宿主）
和 `dsh-bio-gem`（代谢模型专科）构成 g 系产品家族：

| 插件 | 隐喻 | 职责 |
|---|---|---|
| **genie** | 许愿 | 通用生信宿主：50+ 语义化工具 + 自举 Python 环境 + 出版级绘图 |
| **gem** | 晶石（模型资产） | 基因组尺度代谢模型：构建/验证/补洞/账本 |
| **graft** | 嫁接（序列变更） | 基因编辑设计：sgRNA 候选 / 评分向量 / 脱靶扫描 / EditPlan 账本 |

## 接入状态（2026-09-14）

| 能力 | 状态 |
|---|---|
| `graft_*` 工具注册（与 genie 工具同实例共存） | ✅ 已实现 |
| `graft-expert` skill（经 `ctx.skills.register` 汇入 agent 的 skill 目录） | ✅ 已实现 |
| hosted-domain integration 协议（`/api/dsh-bio-graft/integration/health`、`/v1/status`） | ⚠️ **载荷仍为早期形状**，尚未对齐 `genie/docs/plugin-integration.md` v2 契约（字段名/`checks` 数组/`generatedAt` 等）——批次 B |
| genie 设置面板「基因编辑设计」条件分页 | ❌ **未实现**（早前 README 的说法不成立；genie 侧目前没有任何 graft 引用）——批次 B |
| genie persona 能力域路由（存在性感知） | ❌ 未实现——批次 B |

> 在批次 B 落地前：graft 只能通过**工具注册表**被 agent 直接调用，安装状态不体现在 BioGenie 面板里。
> 计划与任务分解见 `docs/PLAN-2026-09-14.md`（施工依据）与 `docs/ARCHITECTURE.md`（架构）。

## 核心哲学

**desired edit first, tool second** —— 用户描述「要什么编辑」，graft 先比选
modality（nuclease / base editing / prime editing / HDR / paired deletion），
而不是先让用户选工具。

**Score vector，不是综合分** —— 每个 sgRNA 候选保留完整评分向量
（GC / 同聚物 / 自回文 / U6 起始偏好 / seed 序列），**不打「87.3 分」这种
伪精确综合分**；排名由 `graft_rank` / 上层的**声明式 objective** 完成并落账本。

**坐标与几何必须自带口径** —— 候选带 `start_0/end_0`（0-based 半开、含 PAM）与
**`cut_site_0`**，并附 `cut_site_convention`（口径字符串）与 `cut_site_verified`
（该编辑器几何是否已对一手文献核对）。没有口径的数字不许进报告。

**证据分级** —— `graft_profiles` 的每个编辑器带 `verified` + `pam_source`：
`verified=false`（如 Cas12b/Cas13a 当前状态）表示 PAM/几何**尚未核对一手文献**，
下游必须如实转述。

**EditPlan 是可审计科学对象** —— 每次设计迭代不是「重新聊天」，而是
修改/追加一个 `.editplan.json`（append-only `runs/` 账本，run 号单调只增、写入原子、
同名计划默认拒绝覆盖）。可回答「为什么昨天推荐 B、今天推荐 D？」——因为
reference / backend / ranking policy 变了。

**脱靶铁律** —— No computational off-target method may label a design as safe.
工具返回值恒带 `interpretation_boundary`（机器可读边界声明）；0 命中时额外返回
`zero_hit_warning`（列出常见假阴性原因：基因组版本不符 / query 方向 / mismatch 过严 /
N 缺口 / bulge 未启用）。只可说「在当前搜索参数下未检出高分位点」。

## 工具（11 个语义化工具）

| 工具 | 说明 |
|---|---|
| `graft_profiles` | 内置 NucleaseProfile 注册表（PAM/spacer/几何 + `verified`/`pam_source` 证据分级） |
| `graft_design` | PAM 双向扫描枚举 sgRNA + 评分向量 + **切割位点**（IUPAC 感知；FASTA/裸序列/多条 FASTA） |
| `graft_score` | 对已有候选补打评分向量（不打综合分） |
| `graft_rank` | **声明式排名**（pareto / lexicographic / weighted-须显式权重）：输出 `policy_id`+`policy_digest`，被剔除候选带原因，缺数据按 `not_searched` 处理 |
| `graft_offtarget` | Cas-OFFinder 批量脱靶扫描 → **结构化命中** + `search_completeness`（枚举没搜的维度）+ `assessment`（拒绝安全结论）+ `per_guide` 汇总；支持 `preflight_only` 基因组体检、`device=auto` |
| `graft_base_edit` | **碱基编辑设计**（CBE/ABE）：窗口内可编辑碱基 + **bystander** + 密码子后果（synonymous/missense/nonsense/stop_loss）；链语义三件套（反链 C→T 在参考正链上是 G→A）；五层 profile 带 `window_evidence` |
| `graft_strategy` | **多 guide 策略评估**（几何 + 组合事实）：`deletion_pair`（预测缺失区间/长度/连接点/移码）、`paired_nickase`（异链 + 间距）；每对候选附 **pairwise 脱靶组合**（不是风险相加；缺数据=not_searched）；未实现策略（prime_edit/hdr/multiplex）显式拒绝 |
| `graft_validation_plan` | **验证方案**：按模态 + 宿主分档（required/recommended/conditional）+ **EditOutcomeMetrics**（每个指标带分子/分母/assay，禁止裸「efficiency」）+ `cannot_conclude`；植物额外要求嵌合/合子性/可遗传性；引物交接给 genie |
| `graft_backend_status` | 后端探测（`status`）/ OpenCL 设备列表（`devices`）/ 自动安装（`ensure`，仅 Windows） |
| `graft_plan_save` | EditPlan 写入（new / add_run / update_recommendation） |
| `graft_plan_load` | EditPlan 读回（plan + 全部 runs 时间线） |

## 安装（作为 dsh 插件）

```bash
dsh plugin --profile web add @dsh-bio/dsh-bio-graft
```

（无全局 CLI 时：`npx -y @deepseek-ai/dsh plugin --profile web add @dsh-bio/dsh-bio-graft`）

安装后 **无需任何额外准备**即可使用 9 个语义化工具（全部纯标准库 Python 实现，复用
`dsh-bio-genie` 的自举解释器或系统 `python`）；**脱靶扫描**需要 Cas-OFFinder 二进制，
由 `graft_backend_status(action="ensure")` 自动获取（仅 Windows；其他平台手动放置）。

## 运行依赖

| 依赖 | 说明 |
|---|---|
| Python ≥3.10 | 复用 `dsh-bio-genie` 自举环境（`GRAFT_PYTHON` 可显式指定解释器）；graft 的 op 全部为标准库实现 |
| Cas-OFFinder（可选） | 官方 Windows x86-64 二进制 v2.4.1（BSD-3）。`graft_backend_status action=ensure` 自动下载到 `~/.dsh/dsh-bio-graft/bin/` |
| OpenCL 运行时 | Cas-OFFinder 需要 OpenCL 设备（GPU 驱动自带；纯 CPU 运行需 Intel/AMD OpenCL runtime）。`action=devices` 可查；`device=auto` 自动选择 |

> ⚠️ 实测：本机（NVIDIA RTX 3050 + AMD gfx90c）**没有 CPU OpenCL 设备**，传 `C` 会直接报
> `No OpenCL devices found.`——所以默认 `device=auto`，并回显实际使用的设备与选择理由。

## 数据目录

```
~/.dsh/dsh-bio-graft/
├── bin/cas-offinder.exe        # 自动安装的脱靶扫描后端
├── tmp/                        # Cas-OFFinder 输入文件与命中原始输出
└── plans/
    ├── <name>.editplan.json     # 当前推荐 + 最新状态（含 last_run_number 单调计数器）
    └── <name>/runs/             # append-only 账本（001_new.json, 002_add_run.json, …）
```

## 自检与回归

```bash
npm test                 # 工具契约 + 黄金 op + 真实脱靶扫描（52 断言）
GRAFT_STRICT=1 npm test  # 严格模式：探针/跳过一律 FAIL（用于 CI，杜绝静默跳过）
```

## 安全边界（架构级门控，写在 skill 中）

- **Level 0 科研常规**（非致病微生物/细胞系/模式生物）：正常提供设计
- **Level 1 人类 somatic 研究**：可设计 + 脱靶评估，但必须显式提示
  `research design ≠ clinical suitability`
- **Level 2 临床决策**：降级为 evidence/risk-analysis 模式
- **Level 3 germline/可遗传人类编辑、病原体增强**：不进入可执行序列设计

## 许可与第三方

本插件 MIT。**不 bundle 任何许可不兼容的第三方代码**：

- Cas-OFFinder（BSD-3）以**外部二进制**形式由用户机器托管（自动下载/手动放置），详见 `THIRD_PARTY_NOTICES.md`
- FlashFry（GPL-3+）/ PrimeDesign（AGPL+商业双许可）/ inDelphi（非商业）/
  CRISPResso2（非商业学术 EULA）→ 一律 **external adapter**，检测到用户合法安装时接入

## 能力批次

| 批次 | 内容 | 状态 |
|---|---|---|
| A | 可信底座：FASTA/IUPAC/Cas-OFFinder 真实契约/cut_site/账本加固 + 测试网 | ✅ 完成 |
| B | 契约化接入：integration v2 载荷 + `capabilities.json` + genie 侧域注册表/条件分页/persona 路由 | 计划中 |
| C | 脱靶语义层（per-guide 汇总/seed 分布）+ 声明式 `graft_rank` + EditPlan 0.2 收口 | 计划中 |
| D | 碱基编辑（BaseEditorProfile + `graft_base_edit` + bystander/密码子后果） | 计划中 |

> 版本号只递增 patch（0.1.1 → 0.1.2 …）；批次名不使用版本号，避免与 npm 版本混淆。

## 架构

见 `docs/ARCHITECTURE.md`。集成协议见 `src/integration.js`；编辑器几何的证据状态见 `docs/PROFILES-TODO.md`。

---

*Part of the **dsh-bio** plugin family · `@dsh-bio/dsh-bio-graft`*
