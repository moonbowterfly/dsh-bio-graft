"""dsh-bio-graft Python 操作层 — JSON 协议分发器（基因编辑设计 v0.1）。

协议与 dsh-bio-genie/dsh-bio-gem 同族：
  TS 侧通过 stdin 发送 {"op": "...", "args": {...}}，
  本脚本执行后 {"ok": true, "result": ...} 或 {"ok": false, "error": "..."} 写 stdout。

契约（bridge 层继承自 gem 模式）：
  - 捕获所有代码异常后恒返回 ok:true，traceback 写 stderr（带 "Traceback (most recent call last)" 头）；
    代码级失败判定在 TS 侧检测该头 → needs_repair=true
  - 输出前 _sanitize_json 递归规范化（-0.0→0.0, NaN/inf→null），规避 dsh snapshot 校验

v0.1 op 一览（对齐 GPT 评审裁决的 MVP 切法）：
  profile_list        列出内置 NucleaseProfile（SpCas9/Cas12a/Cas12b/Cas13/BaseEditor 摘要）
  guide_enumerate     PAM 扫描枚举 sgRNA 候选（NucleaseProfile 驱动 PAM grammar）
  guide_score         on-target 评分向量（ scorecard 类 rule-set，不打综合分）
  offtarget_scan      Cas-OFFinder 后端（Windows 二进制，BSD-3）批量脱靶扫描
  plan_create         生成/更新 EditPlan（.editplan.json，append-only run 记录）
  plan_load           读 EditPlan 汇总（candidates/risk_flags/provenance）
"""
from __future__ import annotations

import json
import os
import sys

# ⚠️ -I（isolated）模式下脚本目录不进 sys.path（dsh 用 -I 调用）——
# 必须显式插入，否则 editors/guides/plans 等同目录模块全部 ModuleNotFoundError。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    # stdout 必须 UTF-8（JSON 契约）；stderr 同样要 UTF-8 —— 否则中文异常信息
    # 按控制台 GBK 编码写出，进 traceback → TS 桥把乱码当成「需要修复」的线索给 agent。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from editors import EDITORS, get_editor
from guides import enumerate_guides, score_guides
from offtarget import casoffinder_scan, locate_casoffinder, ensure_casoffinder
from plans import plan_create, plan_load


def _sanitize_json(obj):
    """递归把 -0.0/NaN/inf 规范成 dsh lossless-safe JSON。"""
    if isinstance(obj, float):
        if obj != obj:  # NaN
            return None
        if obj in (float('inf'), float('-inf')):
            return None
        if obj == 0.0:
            return 0.0  # 归一 -0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


OPS = {
    'profile_list': lambda args: {'editors': [e.public_summary() for e in EDITORS.values()]},
    'profile_get':  lambda args: get_editor(args['editor']).public_summary(),
    'guide_enumerate': lambda args: enumerate_guides(**args),
    'guide_score': lambda args: score_guides(**args),
    'offtarget_scan': lambda args: casoffinder_scan(**args),
    'offtarget_backend': lambda args: {'backend': locate_casoffinder()},
    'offtarget_ensure': lambda args: ensure_casoffinder(),
    'plan_create': lambda args: plan_create(**args),
    'plan_load': lambda args: plan_load(**args),
}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        op = payload.get('op')
        args = payload.get('args') or {}
        if op not in OPS:
            print(json.dumps({'ok': False, 'error': f'unknown op: {op}'}, ensure_ascii=False))
            return 0
        result = OPS[op](args)
        print(json.dumps({'ok': True, 'result': _sanitize_json(result)}, ensure_ascii=False))
    except KeyError as e:
        print(json.dumps({'ok': False,
                          'error': f'missing required arg: {e} (hint: 见该 op 的 tools.js parameters)'},
                         ensure_ascii=False))
    except Exception as e:
        # 恒 ok:true 由桥契约约束——但 op 层失败我们 **显式** ok:false（代码级失败走 stderr traceback）
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False))
        raise  # 让 traceback 进 stderr → TS 层 needs_repair=true
    return 0


if __name__ == '__main__':
    sys.exit(main())
