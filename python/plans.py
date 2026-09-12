"""plans.py — EditPlan 资产（.editplan.json）+ append-only runs 账本。

核心哲学（GPT 评审裁决采纳）：graft 的灵魂不是 sgRNA 设计本身，而是
**EditPlan + multi-objective evidence ranking** —— 传统工具给"一堆 guide 和分数"，
graft 让 agent 能在**可审计科学对象**上做决策："为什么 guide B 排在 guide D 之前"。

目录布局（~/.dsh/dsh-bio-graft/plans/<plan-name>/）：
  <plan-name>.editplan.json    （当前推荐 + 最新状态）
  runs/                        （append-only：001_target_resolution.json, ...）
    002_guide_generation.json
    003_offtarget.json
    004_rerank.json
    005_validation.json

EditPlan schema（v0.1）：
  schema_version
  intent {target, desired_change, modality}
  reference {organism, assembly, sequence_hash, annotation_version}
  editor_profile
  candidates[] {protospacer/pam/coords/scores/off_target_summary/warnings/evidence}
  selected_candidate
  validation_plan
  provenance {tool_versions, model_versions, parameters, database_hashes, timestamp}
  risk_flags
"""
from __future__ import annotations

import json
import os

GRAFT_DATA = os.path.expanduser('~/.dsh/dsh-bio-graft')
PLANS_DIR = os.path.join(GRAFT_DATA, 'plans')


def _plans_root(user_root=None):
    return user_root or PLANS_DIR


def _next_run_number(runs_dir: str) -> int:
    if not os.path.isdir(runs_dir):
        return 1
    return len([f for f in os.listdir(runs_dir) if f.endswith('.json')]) + 1


def plan_create(plan_name: str, intent: dict | None = None, reference: dict | None = None,
                editor_profile: dict | None = None,
                candidates: list | None = None,
                validation_plan: dict | None = None,
                risk_flags: list | None = None,
                plan_dir: str | None = None,
                action: str = 'new',
                provenance: dict | None = None) -> dict:
    """创建/更新 EditPlan。action ∈ {new, add_run, update_recommendation}。

    语义：
      new                —— 创建新 EditPlan + 首个 run 条目
      add_run            —— 追加一条 run 记录（如 003 off-target 结果）；
                            candidates/entries 参数进 run，不改主 plan
      update_recommendation —— 用 candidates 列表重排主 plan 的 recommendation
    """
    if not plan_name:
        raise ValueError('plan_name required')
    safe = ''.join(c for c in plan_name if c.isalnum() or c in '-_.')
    if not safe:
        raise ValueError('plan_name invalid')
    root = _plans_root(plan_dir)
    plan_path = os.path.join(root, f'{safe}.editplan.json')
    runs_dir = os.path.join(root, safe, 'runs')
    os.makedirs(runs_dir, exist_ok=True)
    import time
    ts = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())

    entry = {
        'ts': ts,
        'action': action,
        'provenance': provenance or {},
    }
    if action == 'new':
        plan = {
            'schema_version': '0.1',
            'plan_name': safe,
            'intent': intent or {},
            'reference': reference or {},
            'editor_profile': editor_profile or {},
            'candidates': [],
            'selected_candidate': None,
            'validation_plan': validation_plan or {},
            'provenance': {'created_at': ts, **(provenance or {})},
            'risk_flags': risk_flags or [],
            'history': [],
        }
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=1)
        entry['intent'] = intent
        entry['editor_profile'] = editor_profile
    elif action == 'add_run':
        if not os.path.exists(plan_path):
            raise FileNotFoundError(plan_path)
        plan = json.load(open(plan_path, encoding='utf-8'))
        # 传啥就写啥 run
        if candidates is not None:
            entry['entries'] = candidates
        elif validation_plan is not None:
            entry['validation_plan'] = validation_plan
        elif reference is not None:
            entry['reference'] = reference
        elif editor_profile is not None:
            entry['editor_profile'] = editor_profile
        elif risk_flags is not None:
            entry['risk_flags'] = risk_flags
    elif action == 'update_recommendation':
        if not os.path.exists(plan_path):
            raise FileNotFoundError(plan_path)
        plan = json.load(open(plan_path, 'e' if False else 'utf-8'))
        if candidates is not None:
            plan['candidates'] = candidates
            if candidates and isinstance(candidates[0], dict):
                # 排好序的第一条为推荐（具体排法在 TS/agent 层）
                plan['selected_candidate'] = candidates[0]
        plan.setdefault('history', []).append({'ts': ts, 'event': 'recommendation updated'})
        entry['updated'] = True
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=1)
    else:
        raise ValueError(f'unknown action {action!r}')

    idx = _next_run_number(runs_dir)
    run_file = os.path.join(runs_dir, f'{idx:03d}_{action}.json')
    with open(run_file, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
    return {'ok': True, 'plan_path': plan_path, 'run_file': run_file,
            'run_number': idx, 'action': action}


def plan_load(plan_path: str) -> dict:
    if not os.path.exists(plan_path):
        raise FileNotFoundError(plan_path)
    plan = json.load(open(plan_path, encoding='utf-8'))
    runs_dir = os.path.join(os.path.dirname(plan_path), 'runs')
    runs = []
    if os.path.isdir(runs_dir):
        for f in sorted(os.listdir(runs_dir)):
            if f.endswith('.json'):
                runs.append({'file': f, 'content': json.load(open(os.path.join(runs_dir, f), encoding='utf-8'))})
    return {'plan': plan, 'runs': runs, 'n_runs': len(runs)}
