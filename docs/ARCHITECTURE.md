# dsh-bio-graft 架构

> 更新：2026-09-14（批次 A 完成后）。与 `docs/PLAN-2026-09-14.md` 配套阅读。

## 1. 定位与形态

graft 是 dsh 生态里的**感知式域插件**（hosted-domain extension）：独立 npm 包、独立生命周期，
与宿主 `dsh-bio-genie` **平级**（dsh 没有父子插件机制）。共存时：

```
┌───────────────────────────── dsh 实例（同一 cordis 容器）─────────────────────────────┐
│  genie 插件（宿主）                        graft 插件（域）                            │
│  · bio_* 工具（通用序列/作图/检索/执行器）  · graft_* 工具（编辑设计语义）              │
│  · persona.md（systemPrompt：能力域路由）   · skills/graft-expert（域指引）             │
│  · 设置面板 RPC /api/dsh-bio-genie/*        · integration API /api/dsh-bio-graft/*      │
│  · Python 自举环境 ~/.dsh/dsh-bio-genie/python-env  ←── graft 的解释器解析链首选        │
└─────────────────────────────────────────────────────────────────────────────────────┘
          ▲ 探测（模块解析 + HTTP 只读协议）                    ▲ 数据目录
          └────────────────────────────────────────────  ~/.dsh/dsh-bio-graft/
```

三条跨插件通道（均已实测）：
1. **工具注册表**（agent 可见）—— `graft_*` 与 `bio_*` 同实例共存，agent 按其 description 选择。
2. **skill 平面** —— 宿主 preset 已挂 `skill-filesystem` + `tool-skill` ⇒ 插件经
   `ctx.skills.register()` 注册的 skill 对 agent 可达（会话实测：`bio-core` / `gem-expert` 均可加载）。
3. **常驻上下文路由** —— 宿主的 `prompts/persona.md`；**域路由必须存在性感知**，
   否则插件未安装时 agent 会照着静态路由去调不存在的工具。

第四通道（本插件的）**integration API** 供宿主读取 graft 状态，方向为宿主→graft，只读：
```
GET /api/dsh-bio-graft/integration/health     # 静态：身份 + 协议版本 + features（不 spawn Python、不写盘）
GET /api/dsh-bio-graft/integration/v1/status  # 运行时：state/checks/generatedAt/data/env/remediations
```
> ⚠️ 当前载荷是**早期形状**（`plugin`/`protocol:{major,minors}`，`checks` 为对象而非数组）——
> 与 `genie/docs/plugin-integration.md` v2 契约不一致，批次 B 对齐；在此之前宿主的六态适配器
> 会把 graft 判为 `installed-unavailable`。

## 2. 进程与状态模型

```
agent 工具调用
   └─ src/tools.js（defineTool：schema/description 是 agent 可见的唯一真相）
        └─ src/python.js  callGraft(op, args)
             └─ spawn <python> -I python/graft_ops.py   ← **每次调用都是全新子进程**
                  └─ OPS[op](args)  →  {"ok":true,"result":...} 写 stdout（UTF-8）
                                    代码级失败 → traceback 写 stderr（UTF-8）
```

**跨调用状态只能放 TS 层或磁盘**（Python 侧进程退出即清零）。当前 graft 是无状态设计：
缓存/限流不是 graft 的痛点（无网络请求），持久状态只有磁盘资产（EditPlan、tmp 中间文件）。

契约要点（与 genie/gem 同族）：
- stdout 最后一行是 JSON；**stderr 出现 `Traceback (most recent call last)` = 代码级失败**（TS 侧判定 `needs_repair`）。
- 输出前 `_sanitize_json`（`-0.0→0.0`、`NaN/Inf→null`）——dsh 引擎拒绝非 lossless JSON。
- **stdout 与 stderr 都必须 UTF-8**：否则中文异常在 GBK 控制台编码成乱码，被 TS 桥当作修复线索传给 agent。
- `-I`（isolated）模式脚本目录不进 `sys.path` → `graft_ops.py` 显式 `sys.path.insert`。

## 3. 模块职责

| 模块 | 职责 | 关键不变量 |
|---|---|---|
| `python/sequtil.py` | 序列规范化（FASTA/多行/多条）、反向互补、GC | 清洗规则**单点实现**（旧实现分散导致贪婪正则吞序列的缺陷） |
| `python/editors.py` | `NucleaseProfile` 注册表 | PAM/spacer/几何**只此一处**；带 `verified`/`pam_source` 证据分级 |
| `python/guides.py` | 候选枚举 + 评分向量 + 切割位点 | IUPAC 感知 PAM；坐标口径写进返回值；不打综合分 |
| `python/rank.py` | 声明式排名（hard filter / lexicographic / pareto / weighted-显式权重） | 秩是 policy-dependent（返回 policy_id+digest）；**禁隐式加权**；缺数据=not_searched 必须剔除说明 |
| `python/base_editors.py` | `BaseEditorProfile` 五层注册表（targeting/chemistry/activity/evidence/applicability） | 窗口数字必须来自一手文献（带 `window_evidence`）；**geometry 与 efficiency 彻底分开**，不内置效率预测 |
| `python/base_edit.py` | 碱基编辑设计（窗口内可编辑碱基 + bystander + 密码子后果） | 链语义三件套（反链 C→T = 参考正链 G→A）；缺 CDS 声明→`not_applicable` 不猜读码框 |
| `python/offtarget.py` | Cas-OFFinder 后端（组装输入/设备选择/解析/体检） | 三段式 input；`interpretation_boundary` 恒在；0 命中必带排查提示 |
| `python/plans.py` | EditPlan 资产 + append-only 账本 | run 号单调只增；原子写；同名不覆盖 |
| `python/graft_ops.py` | JSON 协议分发器 | op 注册表是 TS 工具层的对端（契约测试双向校验） |
| `src/tools.js` | 工具注册（7 个） | schema 里 object 型参数必须显式 `additionalProperties` |
| `src/python.js` | 解释器解析链 + 子进程调用 | 候选顺序：`GRAFT_PYTHON` → genie 自举环境 → `CONDA_PREFIX` → `PATH`（逐个探测可导入） |
| `src/skills.js` | `graft-expert` 注册 | 必须带 `name/description/source/provider/content`（缺任一 → 引擎报 `source must be a string`） |
| `src/integration.js` | integration API 路由 | loopback-only 守卫；health 不做昂贵探测 |

## 4. 坐标与几何口径（报告必须携带）

| 字段 | 含义 |
|---|---|
| `start_0` / `end_0` | 0-based 半开区间 `[start, end)`，**含 PAM** |
| `start_1` / `end_1` | 1-based 等价表示 |
| `cut_site_0` | 0-based，切点位于 `cut_site_0-1` 与 `cut_site_0` 两碱基之间 |
| `cut_site_convention` | 口径字符串（如 `SpCas9: cut_site_0 = PAM 起点 − 3 (blunt)`） |
| `cut_site_verified` | 该编辑器几何是否已对一手文献核对（来自 profile） |
| 3′ PAM 系 | `cut_site_0 = PAM 起点 − cut_offset`（SpCas9：−3，平末端） |
| 5′ PAM 系 | `cut_site_0 = PAM 起点 + cut_offset`（Cas12a：+18，错口主切点） |
| Cas-OFFinder | 输出的 `position_0based` 为 **0-based**（Bowtie 约定；工具同时给 1-based 回显） |

## 5. 证据分级纪律

| 级别 | 含义 | 处置 |
|---|---|---|
| 一手文献已核 | profile `verified=true` + `pam_source` 引用 | 可引用 |
| 未核/存疑 | `verified=false`（当前：Cas12b、Cas13a） | 报告必须标注未验证，不得当既定事实 |
| 计算事实 | 工具输出（含 `_provenance`） | 可直接引用 |
| 未检出 | 脱靶扫描 0 命中 | **只能说「在当前参数下未检出」**；0 命中返回排查提示 |

## 6. 测试与验证分层

| 层 | 文件 | 覆盖 |
|---|---|---|
| 工具/op 契约 | `test/tools-contract.mjs` | 工具集合、`additionalProperties`、tools.js↔graft_ops.py 的 op 双向存在性 |
| 黄金 op | `test/golden-ops.mjs` | FASTA/多行输入、IUPAC PAM、cut_site 口径、账本序号单调/同名保护 |
| 真实后端 | `test/offtarget-scan.mjs` | 真实 Cas-OFFinder：精确命中坐标、1-mismatch 错配位置、0 命中护栏、长度校验、缺基因组引导 |
| 接入协议 | `test/integration-contract.mjs`（批次 B） | v2 载荷形状与 state 一致性 |
| 真实会话 | `D:\Program\dsh\graft-plan-e2e` + 驱动脚本 | agent 真会用（配对 tool/call 与 tool/result）、无自愈 |
| 宿主适配器 | genie `scripts/test-graft-adapter.mjs`（批次 B） | 六态矩阵 + gem 零漂移 |

纪律：`GRAFT_STRICT=1` 下探针失败/跳过一律 FAIL（门不许静默跳过）。

## 7. 扩展点（按批次）

- **批次 B**：integration v2 载荷、`capabilities.json`、genie 域注册表/条件分页/persona 路由。
- **批次 C**：`graft_rank`（声明式 policy + Pareto）、off-target per-guide 语义汇总（seed 区分布）、
  EditPlan 0.2 的 `ranking_policy`/`off_target_summary` 收口。
- **批次 D**：`BaseEditorProfile` + `graft_base_edit`（窗口可编辑碱基/bystander/密码子后果）。
- 之后（触发条件另议）：prime editing、CRISPRi/a + Cas13 designer、HDR 供体、编辑结果 ML 预测（provider 化）。

**永不 bundle**：FlashFry（GPL-3+）、PrimeDesign（AGPL/商业）、inDelphi（非商业）、CRISPResso2（非商业学术 EULA）。
