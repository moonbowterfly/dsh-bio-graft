"""plans.py — EditPlan 资产（.editplan.json）+ append-only runs 账本。

核心哲学：graft 的灵魂不是 sgRNA 设计本身，而是 **EditPlan + 多目标证据排序** ——
传统工具给"一堆 guide 和分数"，graft 让 agent 在**可审计科学对象**上做决策：
「为什么 guide B 排在 guide D 之前」——答案在 runs/ 账本里，而不在对话记忆里。

目录布局（~/.dsh/dsh-bio-graft/plans/）：
  <plan-name>.editplan.json     当前推荐 + 最新状态（含 last_run_number 单调计数器）
  <plan-name>/runs/             append-only 时间线（001_new.json, 002_add_run.json, …）

EditPlan schema（0.2）：
  schema_version / plan_name
  intent {target, desired_change, modality}
  reference {organism, assembly, sequence_hash, annotation_version}
  editor_profile           来自 graft_profiles
  candidates[] / selected_candidate
  ranking_policy           声明的排序策略（objective/weights/tie_breakers/hard_filters）
  off_target_summary       脱靶扫描摘要（per-guide 计数 + 搜索参数 + 边界声明引用）
  coordinate_systems       坐标与切点口径（与 guides.COORDINATE_SYSTEM 一致）
  validation_plan / risk_flags
  provenance / history / last_run_number

2026-09-14 加固（D6）：
  ① 序号单调只增（目录最大序号 与 plan.last_run_number 取大者 + 1）——
     旧实现用「文件数 + 1」，删掉中间 run 后撞号 = 重写审计历史；
  ② 全部写入原子（临时文件 + os.replace），崩溃不留半截 JSON；
  ③ plan_create(new) 默认拒绝覆盖同名计划（审计禁忌），需显式 overwrite=True；
  ④ add_run 记录**所有**传入字段（旧实现 if/elif 只记第一个，其余静默丢弃）；
  ⑤ plan_load 支持 plan_name（旧实现只接受绝对路径）；
  ⑥ plan_name 非法字符响亮报错（旧实现静默剥离）。
"""
from __future__ import annotations

import json
import os
import re
import time

GRAFT_DATA = os.path.expanduser('~/.dsh/dsh-bio-graft')
PLANS_DIR = os.path.join(GRAFT_DATA, 'plans')
SCHEMA_VERSION = '0.2'

COORDINATE_SYSTEMS = {
    'guide': 'start_0/end_0 = 0-based 半开区间 [start, end)，含 PAM；start_1/end_1 = 1-based',
    'cut': 'cut_site_0 位于 cut_site_0-1 与 cut_site_0 两碱基之间；cut_site_verified=False '
           '表示该编辑器几何尚未核对一手文献',
}


def _plans_root(user_root=None):
    return user_root or PLANS_DIR


def _safe_plan_name(plan_name: str) -> str:
    if not plan_name:
        raise ValueError('plan_name required')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', plan_name):
        raise ValueError(
            f'plan_name {plan_name!r} 含不安全字符；只允许 [A-Za-z0-9._-]'
            f'（旧实现会静默剥掉非法字符 → 落盘名与用户预期不一致，故改为响亮报错）')
    return plan_name


def _next_run_number(runs_dir: str, floor: int = 0) -> int:
    """下一个 run 号 = max(现有最大序号, floor) + 1。

    🔴 为什么不是「文件数 + 1」（旧实现，实测 D6）：删掉中间 run 后会撞号，
    等于**重写审计历史**；审计对象一旦被引用过（报告里写「见 run 003」），
    号码复用就是数据损坏。
    🔴 为什么还要 floor：文件被删后光看目录无法知道曾经用到几号，
    所以把 `last_run_number` 单调记在 plan 主对象里，序号只增不减。
    """
    nums = []
    if os.path.isdir(runs_dir):
        for f in os.listdir(runs_dir):
            m = re.match(r'^(\d{3})_.*\.json$', f)
            if m:
                nums.append(int(m.group(1)))
    nums.append(int(floor or 0))
    return max(nums) + 1


def _atomic_write_json(path: str, payload) -> None:
    """临时文件 + os.replace：崩溃不会留下半截 JSON。"""
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path: str):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _resolve_plan_path(plan_path: str | None, plan_name: str | None, root: str) -> str:
    if plan_path:
        return plan_path
    if not plan_name:
        raise ValueError('plan_path or plan_name required（plan_name 走默认 plans 目录）')
    return os.path.join(root, f'{_safe_plan_name(plan_name)}.editplan.json')


def plan_create(plan_name: str, intent: dict | None = None, reference: dict | None = None,
                editor_profile: dict | None = None,
                candidates: list | None = None,
                validation_plan: dict | None = None,
                risk_flags: list | None = None,
                ranking_policy: dict | None = None,
                off_target_summary: dict | None = None,
                plan_dir: str | None = None,
                action: str = 'new',
                overwrite: bool = False,
                provenance: dict | None = None) -> dict:
    """创建/追加 EditPlan。action ∈ {new, add_run, update_recommendation}。

    语义：
      new                    —— 创建新 EditPlan + 首个 run（同名已存在时拒绝，需 overwrite=True）
      add_run                —— 追加一条 run（记录所有传入字段，不静默丢弃）
      update_recommendation  —— 用 candidates 更新主 plan 的推荐（排序由 graft_rank/agent 定）
    """
    safe = _safe_plan_name(plan_name)
    root = _plans_root(plan_dir)
    plan_path = os.path.join(root, f'{safe}.editplan.json')
    runs_dir = os.path.join(root, safe, 'runs')
    os.makedirs(runs_dir, exist_ok=True)
    ts = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())

    entry = {'ts': ts, 'action': action, 'provenance': provenance or {}}
    plan = None
    existed = os.path.exists(plan_path)

    if action == 'new':
        if existed and not overwrite:
            raise FileExistsError(
                f'{plan_path} 已存在；覆盖会丢失历史（审计禁忌）。'
                f'请改用 action="add_run"/"update_recommendation"，或显式 overwrite=True')
        plan = {
            'schema_version': SCHEMA_VERSION,
            'plan_name': safe,
            'intent': intent or {},
            'reference': reference or {},
            'editor_profile': editor_profile or {},
            'candidates': [],
            'selected_candidate': None,
            'ranking_policy': ranking_policy or {},
            'off_target_summary': off_target_summary or {},
            'coordinate_systems': COORDINATE_SYSTEMS,
            'validation_plan': validation_plan or {},
            'provenance': {'created_at': ts, **(provenance or {})},
            'risk_flags': risk_flags or [],
            'history': [],
            'last_run_number': 0,
        }
        _atomic_write_json(plan_path, plan)
        entry['intent'] = intent
        entry['editor_profile'] = editor_profile
        if ranking_policy is not None:
            entry['ranking_policy'] = ranking_policy

    elif action == 'add_run':
        if not existed:
            raise FileNotFoundError(f'{plan_path}（先用 action="new" 创建计划）')
        plan = _read_json(plan_path)
        # 记录**所有**传入字段（旧实现 if/elif 只记第一个 → 其余静默丢失）
        if candidates is not None:
            entry['entries'] = candidates
        if validation_plan is not None:
            entry['validation_plan'] = validation_plan
        if reference is not None:
            entry['reference'] = reference
        if editor_profile is not None:
            entry['editor_profile'] = editor_profile
        if risk_flags is not None:
            entry['risk_flags'] = risk_flags
        if ranking_policy is not None:
            entry['ranking_policy'] = ranking_policy
        if off_target_summary is not None:
            entry['off_target_summary'] = off_target_summary
        content_keys = ('entries', 'validation_plan', 'reference', 'editor_profile',
                        'risk_flags', 'ranking_policy', 'off_target_summary')
        if not any(k in entry for k in content_keys) and not entry['provenance']:
            raise ValueError('add_run 至少要传一个待记录字段（candidates/validation_plan/'
                             'reference/editor_profile/risk_flags/ranking_policy/'
                             'off_target_summary）或非空 provenance')

    elif action == 'update_recommendation':
        if not existed:
            raise FileNotFoundError(f'{plan_path}（先用 action="new" 创建计划）')
        plan = _read_json(plan_path)
        if candidates is not None:
            plan['candidates'] = candidates
            if candidates and isinstance(candidates[0], dict):
                # 排好序的第一条为推荐（排法来自 graft_rank 的声明式 policy）
                plan['selected_candidate'] = candidates[0]
        if ranking_policy is not None:
            plan['ranking_policy'] = ranking_policy
            entry['ranking_policy'] = ranking_policy
        if off_target_summary is not None:
            plan['off_target_summary'] = off_target_summary
            entry['off_target_summary'] = off_target_summary
        plan.setdefault('history', []).append({'ts': ts, 'event': 'recommendation updated'})
        entry['updated'] = True

    else:
        raise ValueError(f'unknown action {action!r}')

    idx = _next_run_number(runs_dir, floor=int((plan or {}).get('last_run_number') or 0))
    run_file = os.path.join(runs_dir, f'{idx:03d}_{action}.json')
    _atomic_write_json(run_file, entry)

    # 单调计数器落盘（序号只增不减，即使有人删除了 run 文件）
    if int(plan.get('last_run_number') or 0) != idx:
        plan['last_run_number'] = idx
        _atomic_write_json(plan_path, plan)

    return {'ok': True, 'plan_path': plan_path, 'run_file': run_file,
            'run_number': idx, 'action': action, 'schema_version': SCHEMA_VERSION}


def plan_load(plan_path: str | None = None, plan_name: str | None = None,
              plan_dir: str | None = None) -> dict:
    """读回 EditPlan 主对象 + 完整 runs 时间线（run 文件名排序即时间顺序）。"""
    root = _plans_root(plan_dir)
    path = _resolve_plan_path(plan_path, plan_name, root)
    if not os.path.exists(path):
        raise FileNotFoundError(f'{path}（不存在；可用 graft_plan_save 先创建）')
    plan = _read_json(path)
    name = plan.get('plan_name') or os.path.basename(path).replace('.editplan.json', '')
    runs_dir = os.path.join(os.path.dirname(path), name, 'runs')
    if not os.path.isdir(runs_dir):
        # 兼容旧布局（plans/runs/ 直挂）——仅当按名目录不存在时回退
        legacy = os.path.join(os.path.dirname(path), 'runs')
        if os.path.isdir(legacy):
            runs_dir = legacy
    runs = []
    if os.path.isdir(runs_dir):
        for f in sorted(os.listdir(runs_dir)):
            if f.endswith('.json'):
                runs.append({'file': f,
                             'content': _read_json(os.path.join(runs_dir, f))})
    return {'plan': plan, 'runs': runs, 'n_runs': len(runs),
            'plan_path': path, 'runs_dir': runs_dir}
