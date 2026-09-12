# THIRD PARTY NOTICES — dsh-bio-graft

本插件自身以 MIT 许可分发（见 `LICENSE`）。以下第三方组件以**非捆绑**方式使用：
graft 不复制、不分发其源码或二进制；由用户的机器在需要时从其官方发布渠道获取。

---

## Cas-OFFinder

- **用途**：脱靶位点批量扫描后端（`graft_offtarget` 调用）
- **来源**：https://github.com/snugel/cas-offinder
- **版本**：v2.4.1（官方 Windows x86-64 release asset）
- **许可**：BSD 3-Clause License
- **获取方式**：用户通过 `graft_backend_status action=ensure` 触发自动下载
  （保存至 `~/.dsh/dsh-bio-graft/bin/cas-offinder.exe`），或手动下载放置。
- **说明**：graft 仅以子进程调用该可执行文件并解析其输出，不修改、不重分发其代码。
  若您的使用场景需要重新分发 Cas-OFFinder 二进制，请遵循其 BSD-3-Clause 条款
  （保留版权声明与免责声明）。

---

## 参考但未引入的实现（设计参考，无代码复制）

以下项目仅在 graft 的**设计文档与接口语义**中作为公开文献/工程实践参考，
graft 不包含其任何代码：

| 项目 | 许可 | 参考内容 |
|---|---|---|
| crisprVerse / crisprBase | MIT | NucleaseProfile 对象化设计思路 |
| CRISPOR / CHOPCHOP | academic / Apache-2.0 | 评分维度与报告字段设计参考 |
| FlashFry | GPL-3.0-or-later | 高吞吐 guide 表征的接口设计参考（**绝不 bundle**） |
| PrimeDesign | AGPL-3.0 + 商业双许可 | pegRNA 设计字段设计参考（**绝不 bundle**） |
| inDelphi / BE-Hive / DeepBE | 非商业研究许可 | 编辑结果预测的 provider 化边界参考（**绝不 bundle**） |
| CRISPResso2 | 非商业学术 EULA | 编辑后测序分析 adapter 的边界参考（**绝不 bundle**） |

上述项目如经用户合法安装，graft 未来可通过 **external adapter** 方式（检测本地安装、
子进程调用）接入；graft 本体永不内嵌其代码。
