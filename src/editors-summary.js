// editors-summary.js — 编辑器注册表的**只读静态摘要**（供 integration status 与面板展示）。
//
// 为什么是静态的：契约要求 health/status 不做昂贵探测（不 spawn Python）。真正的
// 单一事实源仍然是 python/editors.py —— 本文件是它的**缓存副本**，由
// test/integration-contract.mjs 用真实 profile_list op 逐字段比对，任何漂移都会让
// `npm test` 变红（改 editors.py 后两个地方一起改，测试会告诉你有没有漏）。
export const EDITORS_SUMMARY = [
  {
    name: 'SpCas9', casualName: 'Cas9 (Sp, NGG)', pam: 'NGG', pamSide: '3prime',
    spacerLength: 20, targetType: 'DNA', cutOffset: 3, cutStructure: 'blunt',
    verified: true, pamSource: 'Jinek 2012 Science 337:816（SpCas9 需 NGG PAM；平末端切点在 PAM 上游 3 bp）',
  },
  {
    name: 'SpCas9-NG', casualName: 'Cas9-NG (NG)', pam: 'NG', pamSide: '3prime',
    spacerLength: 20, targetType: 'DNA', cutOffset: 3, cutStructure: 'blunt',
    verified: true, pamSource: 'Nishimasu 2018 Science 361:1259（SpCas9-NG，NG PAM）',
  },
  {
    name: 'SpG', casualName: 'SpG (NGN)', pam: 'NGN', pamSide: '3prime',
    spacerLength: 20, targetType: 'DNA', cutOffset: 3, cutStructure: 'blunt',
    verified: true, pamSource: 'Walton 2020 Science 368:290（SpG：NGN PAM；SpRY 才近乎 PAM-less）',
  },
  {
    name: 'Cas12a', casualName: "Cpf1 (TTTV, 5prime PAM)", pam: 'TTTV', pamSide: '5prime',
    spacerLength: 20, targetType: 'DNA', cutOffset: 18, cutStructure: 'staggered',
    verified: true, pamSource: 'Zetsche 2015 Cell 163:759（LbCpf1/Cas12a：TTTV PAM，5\' 端 PAM，错口切割）',
  },
  {
    name: 'Cas12b', casualName: 'Cas12b (TTN/TNN — 待核)', pam: 'TTN', pamSide: '5prime',
    spacerLength: 20, targetType: 'DNA', cutOffset: 17, cutStructure: 'staggered',
    verified: false, pamSource: '待核：本机原声明 TNN 与 TTN 存疑；见 docs/PROFILES-TODO.md',
  },
  {
    name: 'Cas13a', casualName: 'Cas13a (RNA targeting)', pam: 'NNN', pamSide: '3prime',
    spacerLength: 22, targetType: 'RNA', cutOffset: 15, cutStructure: 'enzymatic-RNA',
    verified: false, pamSource: '待核：RNA 靶向无 DNA PAM 概念（占位声明）',
  },
]
