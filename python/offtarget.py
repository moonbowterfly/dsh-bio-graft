"""offtarget.py — Cas-OFFinder 后端（BSD-3 官方 Windows x86-64 二进制）。

═══════════════════════════════════════════════════════════════════════════
实测契约（2026-09-14，Cas-OFFinder v2.4.1，探针记录见 test/offtarget-scan.mjs）
═══════════════════════════════════════════════════════════════════════════
CLI：  cas-offinder {input_filename|-} {C|G|A}[device_id(s)] {output_filename|-}

input 文件是**三段式**（旧实现只写「genome 路径 + pattern」两行 → 永远 0 命中）：
    ① 第 1 行 = genome 路径（FASTA 文件或包含 FASTA/2BIT 的目录；正斜杠更稳）
    ② 第 2 行 = pattern —— **必须与 query 等长**（'N20NGG' 这类简写不被接受，
       需展开成 'NNNNNNNNNNNNNNNNNNNNNGG'）
    ③ 第 3 行起 = query（spacer+PAM 字面量）+' '+该 query 允许的 mismatch 数
              （可选：行尾再加标签，会回显到输出）

输出：制表符分隔 6 列，**无表头**，行尾 CRLF：
    query | chromosome | position(0-based) | matched_sequence(错配碱基小写) | strand(+/-) | mismatch 数

设备：CPU 设备需要 OpenCL CPU runtime。本机（RTX 3050 + AMD gfx90c）**没有 CPU
OpenCL 设备** —— 传 'C' 直接报 "No OpenCL devices found."（rc=1），必须用 'G0'。
因此默认 device='auto'：解析可执行文件自报的设备表，优先 CPU（确定性最好），
无 CPU 时按 ID 取第一个 GPU。

bulge：Cas-OFFinder 本体**不支持** bulge 参数（官方用独立包装脚本 cas-offinder-bulge
实现）。本工具对 bulge>0 的请求**响亮报错**，绝不静默忽略。

铁律：任何返回都带 `interpretation_boundary`。计算方法的"未检出"只能表述为
「在当前搜索参数下未检出」——绝不允许被读成「安全」/「无脱靶」。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from offtarget_interpret import (aggregate_per_guide, build_assessment,
                                 build_search_completeness)

CAS_OFFINDER_URL = ('https://github.com/snugel/cas-offinder/releases/download/'
                    '2.4.1/cas-offinder_windows_x86-64.zip')  # x86-64（非 x86_64）
graft_data_dir = os.path.expanduser('~/.dsh/dsh-bio-graft')
graft_bin_dir = os.path.join(graft_data_dir, 'bin')
graft_tmp_dir = os.path.join(graft_data_dir, 'tmp')

INTERPRETATION_BOUNDARY = (
    '本结果只表示「在当前搜索参数下未检出以下位点 / 检出了以下位点」，'
    '**不构成任何「安全」「无脱靶」结论**。未检出的常见原因包括：基因组文件与实验株/'
    '组装版本不符、mismatch 数或 PAM pattern 过严、query 方向写反、参考序列含 N 缺口、'
    '未启用 bulge 搜索，以及计算方法本身的灵敏度上限。'
)

ZERO_HIT_WARNING = (
    '0 命中是一条**待排查信号**，不是结论。请依次核对：① genome_file 是否真的是'
    '目标物种/组装版本（size/record 数见 genome_check）；② query 是否与 pattern 等长且'
    '方向正确；③ mismatch 数是否过严；④ 参考序列是否含大量 N；'
    '⑤ 若怀疑，先用一段已知含该 PAM 位点的小序列做阳性对照。'
)

PAM_PATTERN_SHORTHAND = re.compile(r'([Nn])(\d+)')


def expand_pattern(pattern: str) -> str:
    """展开 Cas-OFFinder pattern 简写：'N20NGG' -> 'NNNNNNNNNNNNNNNNNNNNNGG'。

    实测：Cas-OFFinder 会报 "The length of target sequences should match with the
    length of pattern sequence." —— 简写不被接受。
    """
    return PAM_PATTERN_SHORTHAND.sub(lambda m: m.group(1).upper() * int(m.group(2)), pattern)


def build_casoffinder_input(genome_path: str, pattern: str, queries: list[str],
                            mismatches: int, workdir: str | None = None) -> str:
    """组装 Cas-OFFinder 三段式 input 文件，返回其路径。"""
    if not queries:
        raise ValueError('queries required（至少一条 spacer+PAM 序列）')
    pattern = expand_pattern(pattern)
    bad = sorted({ch for q in queries + [pattern] for ch in q.upper()
                  if ch not in 'ACGTNRYKMSWBDHV'})
    if bad:
        raise ValueError(f'非法字符 {bad}（pattern/query 只允许 IUPAC 碱基码）')
    for q in queries:
        if len(q) != len(pattern):
            raise ValueError(
                f'query {q!r} 长度 {len(q)} 与 pattern {pattern!r} 长度 {len(pattern)} 不一致；'
                f'Cas-OFFinder 要求两者等长')
    workdir = workdir or graft_tmp_dir
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, f'casoffinder_input_{os.getpid()}.txt')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(str(genome_path).replace('\\', '/') + '\n')
        f.write(pattern + '\n')
        for q in queries:
            f.write(f'{q.upper()} {int(mismatches)}\n')
    return path


def list_devices(exe: str, timeout: int = 30) -> list[dict]:
    """解析可执行文件自报的可用设备表（不带参数运行）。

    形如：  Type: GPU, ID: 0, <NVIDIA GeForce RTX 3050 Laptop GPU> on <NVIDIA CUDA>
    返回 [{'type': 'GPU', 'id': 0, 'name': ..., 'platform': ..., 'selector': 'G0'}]
    """
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace')
    except Exception as e:  # noqa: BLE001
        return [{'error': f'{type(e).__name__}: {e}'}]
    out = (r.stdout or '') + (r.stderr or '')
    devices = []
    for m in re.finditer(r'Type:\s*(GPU|CPU|Accelerator),\s*ID:\s*(\d+),\s*<([^>]*)>\s*on\s*<([^>]*)>',
                         out, re.I):
        kind = m.group(1).upper()
        prefix = {'GPU': 'G', 'CPU': 'C', 'ACCELERATOR': 'A'}[kind]
        devices.append({
            'type': kind, 'id': int(m.group(2)), 'name': m.group(3).strip(),
            'platform': m.group(4).strip(),
            'selector': f'{prefix}{m.group(2)}',
        })
    return devices


def pick_device(exe: str, requested: str = 'auto') -> tuple[str, list[dict], str]:
    """选设备：显式请求优先；auto = 先 CPU（确定性）再按 ID 取 GPU。

    返回 (selector, devices, note)。没有可用设备时 selector 为 None 并给 note。
    """
    devices = list_devices(exe)
    if requested and requested.lower() != 'auto':
        return requested, devices, f'显式指定 device={requested}'
    cpus = [d for d in devices if d.get('type') == 'CPU']
    gpus = [d for d in devices if d.get('type') == 'GPU']
    if cpus:
        return 'C', devices, 'auto：检测到 CPU OpenCL 设备，取 CPU（确定性优先）'
    if gpus:
        first = sorted(gpus, key=lambda d: d['id'])[0]
        return first['selector'], devices, (
            f"auto：无 CPU OpenCL 设备，改用 GPU {first['selector']} "
            f"({first['name']} on {first['platform']})")
    return None, devices, '未检测到任何 OpenCL 设备（GPU/CPU 都没有）'


def offtarget_devices() -> dict:
    """列出可用 OpenCL 设备并给出 auto 选择结果（排查「为什么扫描失败」的第一站）。"""
    info = locate_casoffinder()
    if not info.get('ok'):
        return {'backend': info, 'devices': [], 'auto_selected': None,
                'note': 'cas-offinder 未安装：先跑 graft_backend_status(action="ensure")'}
    selector, devices, note = pick_device(info['path'], 'auto')
    return {'backend': info, 'devices': devices, 'auto_selected': selector, 'note': note}


def locate_casoffinder() -> dict:
    """定位 cas-offinder 可执行文件。

    探测顺序：① `GRAFT_CAS_OFFINDER` env（最高优先级）
              ② `~/.dsh/dsh-bio-graft/bin/cas-offinder.exe`（graft 自管目录）
              ③ PATH ④ 与本文件同目录（手动放置）
    """
    env_path = os.environ.get('GRAFT_CAS_OFFINDER')
    if env_path and os.path.exists(env_path):
        return {'path': env_path, 'source': 'GRAFT_CAS_OFFINDER', 'ok': True}
    local = os.path.join(graft_bin_dir, 'cas-offinder.exe')
    if os.path.exists(local):
        return {'path': local, 'source': 'graft-bin', 'ok': True}
    which = shutil.which('cas-offinder')
    if which:
        return {'path': which, 'source': 'PATH', 'ok': True}
    sibling = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cas-offinder.exe')
    if os.path.exists(sibling):
        return {'path': sibling, 'source': 'graft-python-dir', 'ok': True}
    return {
        'path': None, 'source': None, 'ok': False,
        'install_hint': (
            '安装方法 A（自动，仅 Windows）：agent 调 graft_backend_status(action="ensure") '
            '自动下载官方 BSD-3 Windows x86-64 二进制到 ~/.dsh/dsh-bio-graft/bin/。'
            '方法 B（手动）：https://github.com/snugel/cas-offinder/releases 下载 '
            'cas-offinder_windows_x86-64.zip 解压，把 cas-offinder.exe 放到 '
            '~/.dsh/dsh-bio-graft/bin/，或用 GRAFT_CAS_OFFINDER 指向它。'
            '非 Windows 平台请用系统包管理器安装（本插件不代下载跨平台二进制）。'
        ),
        'license': 'BSD-3-Clause (原仓库 LICENSE)',
    }


def ensure_casoffinder() -> dict:
    """下载官方 Windows 二进制（v2.4.1，BSD-3）到 graft bin 目录。幂等。

    平台纪律：只对 Windows 自动下载 .exe；其他平台明确拒绝（不做「装了个不能跑的文件」）。
    校验纪律：GitHub releases **未提供官方校验文件**，故不做假校验；若用户设置
    GRAFT_CAS_OFFINDER_SHA256 则强制比对。
    """
    exe = os.path.join(graft_bin_dir, 'cas-offinder.exe')
    if os.path.exists(exe):
        return {'ok': True, 'path': exe, 'note': 'already present'}
    if sys.platform != 'win32':
        return {'ok': False,
                'error': f'自动安装仅支持 Windows（当前 {sys.platform}）',
                'hint': '请用系统包管理器安装 cas-offinder，或设置 GRAFT_CAS_OFFINDER'}
    os.makedirs(graft_bin_dir, exist_ok=True)
    zip_path = os.path.join(graft_bin_dir, 'cas-offinder_windows.zip')
    sys.stderr.write('[graft] downloading Cas-OFFinder v2.4.1 (BSD-3) ...\n')
    urllib.request.urlretrieve(CAS_OFFINDER_URL, zip_path)

    expected = os.environ.get('GRAFT_CAS_OFFINDER_SHA256')
    if expected:
        digest = hashlib.sha256(open(zip_path, 'rb').read()).hexdigest()
        if digest.lower() != expected.lower():
            os.remove(zip_path)
            return {'ok': False, 'error': 'checksum mismatch',
                    'expected_sha256': expected, 'actual_sha256': digest}
    with zipfile.ZipFile(zip_path) as zf:
        exe_target = None
        for n in zf.namelist():
            if n.lower().endswith('cas-offinder.exe'):
                zf.extract(n, graft_bin_dir)
                exe_target = os.path.join(graft_bin_dir, n)
        if not exe_target:
            zf.extractall(graft_bin_dir)
            exe_target = os.path.join(graft_bin_dir, 'cas-offinder.exe')
        if not os.path.exists(exe_target):
            raise RuntimeError('cas-offinder.exe not found in archive')
        if os.path.dirname(exe_target) != graft_bin_dir:
            os.replace(exe_target, exe)
    os.remove(zip_path)
    probe = subprocess.run([exe], capture_output=True, text=True, timeout=60,
                           encoding='utf-8', errors='replace')
    return {'ok': True, 'path': exe,
            'version_probe_head': ((probe.stdout or '') + (probe.stderr or ''))[:200],
            'checksum': ('user-provided sha256 verified' if expected
                         else 'GitHub releases 未提供官方校验文件；未做校验（可设 '
                              'GRAFT_CAS_OFFINDER_SHA256 强制校验）')}


def genome_preflight(genome_path: str, max_records: int = 5000) -> dict:
    """扫描前的基因组体检（不发车就发现「基因组不对」这类致命输入错误）。

    报告：文件/目录类型、大小、记录数、总 bp、N 比例、是否 CRLF、前 3 条记录名。
    """
    info = {'path': genome_path.replace('\\', '/'), 'exists': os.path.exists(genome_path)}
    if not info['exists']:
        info['ok'] = False
        info['error'] = 'genome path does not exist'
        return info
    if os.path.isdir(genome_path):
        files = [f for f in os.listdir(genome_path)
                 if f.lower().endswith(('.fa', '.fasta', '.fna', '.2bit'))]
        info.update({'kind': 'directory', 'n_files': len(files),
                     'files_sample': sorted(files)[:5],
                     'ok': len(files) > 0})
        if not files:
            info['error'] = '目录下没有 FASTA/2BIT 文件（Cas-OFFinder 需要目录或单个 FASTA 文件）'
        return info

    info['kind'] = 'file'
    info['size_bytes'] = os.path.getsize(genome_path)
    crlf = 0
    n_records = 0
    length = 0
    n_count = 0
    names = []
    with open(genome_path, 'rb') as fb:
        head = fb.read(2 * 1024 * 1024)
    if b'\r\n' in head:
        crlf = head.count(b'\r\n')
    with open(genome_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('>'):
                n_records += 1
                if len(names) < 3:
                    names.append(line[1:].strip().split()[0] if line[1:].strip() else '')
                if n_records >= max_records:
                    break
                continue
            s = line.strip()
            if s:
                length += len(s)
                n_count += s.upper().count('N')
    info.update({
        'n_records': n_records, 'total_bp': length,
        'n_fraction': round(n_count / length, 5) if length else None,
        'record_names_sample': names,
        'crlf_lines_in_first_2MB': crlf,
        'ok': n_records > 0 and length > 0,
    })
    if n_records == 0:
        info['error'] = '不是 FASTA（没有 > 头行）——Cas-OFFinder 无法解析该文件'
    if crlf:
        info['warning'] = ('检测到 CRLF 换行；Cas-OFFinder 一般可解析，但若结果异常请先转 LF')
    return info


def _parse_hits(path: str, top_n: int) -> tuple[list[dict], bool]:
    """解析 Cas-OFFinder 6 列输出（无表头，0-based 坐标，错配碱基小写）。"""
    hits = []
    truncated = False
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) < 6:
                continue
            query, chrom, pos, matched, strand, mm = parts[:6]
            try:
                pos0 = int(pos)
                mm_i = int(mm)
            except ValueError:
                continue
            hits.append({
                'query': query,
                'chromosome': chrom,
                'position_0based': pos0,
                'position_1based': pos0 + 1,
                'matched_sequence': matched,
                'strand': strand,
                'mismatches': mm_i,
                'mismatch_positions_1based': [
                    i + 1 for i, ch in enumerate(matched) if ch.islower()],
            })
            if len(hits) >= top_n:
                truncated = True
                break
    return hits, truncated


def queries_from_candidates(candidates: list, editor: str = 'SpCas9') -> tuple[list[str], str]:
    """把 graft_design 的候选转成 (queries, pattern)。

    3' PAM（SpCas9 系）：query = spacer + PAM 字面量；pattern = 'N'*L + PAM 模式
    5' PAM（Cas12a 系）：query = PAM 字面量 + spacer；pattern = PAM 模式 + 'N'*L
    用**候选自带的字面量 PAM**（而不是 'NGG' 通配）可让每条 query 的搜索面精确到该位点，
    避免不同 PAM 变体互相污染命中集；pattern 仍保留 profile 的 PAM 退化模式，
    以便 Cas-OFFinder 在比对时允许 PAM 位点的简并匹配。
    """
    from editors import get_editor  # 同目录模块（脚本目录由 graft_ops 注入 sys.path）
    profile = get_editor(editor)
    queries = []
    for c in candidates or []:
        spacer = (c.get('protospacer') if isinstance(c, dict) else str(c)) or ''
        pam = (c.get('pam') if isinstance(c, dict) else None) or ''
        spacer = spacer.upper()
        pam = pam.upper()
        if not spacer:
            continue
        if not pam:
            raise ValueError(f'candidate {spacer[:12]}… 缺 pam 字段——'
                             f'请传 graft_design 的原样输出，或用 queries 显式给出序列')
        if len(spacer) != profile.spacer_length:
            raise ValueError(f'candidate spacer 长度 {len(spacer)} 与 {profile.name} 的 '
                             f'{profile.spacer_length} 不符')
        queries.append((spacer + pam) if profile.pam_side == '3prime' else (pam + spacer))
    if not queries:
        raise ValueError('candidates 里没有可用序列')
    pattern = (('N' * profile.spacer_length + profile.pam_pattern)
               if profile.pam_side == '3prime'
               else (profile.pam_pattern + 'N' * profile.spacer_length))
    return queries, pattern


def casoffinder_scan(genome_file: str, *, queries: list[str] | None = None,
                     candidates: list | None = None, editor: str = 'SpCas9',
                     pattern: str | None = None, mismatches: int = 3,
                     device: str = 'auto', top_n: int = 200,
                     output: str | None = None, preflight_only: bool = False,
                     seed_length: int = 8, pam_side: str = '3prime',
                     workdir: str | None = None) -> dict:
    """跑一次 Cas-OFFinder 扫描（三段式 input 组装 + 设备自选 + 结构化解析）。

    queries 与 candidates 二选一：candidates 走 queries_from_candidates 自动派生。
    """
    exe_info = locate_casoffinder()
    if not exe_info.get('ok'):
        return {'ok': False, 'error': 'cas-offinder not found', **exe_info}

    exe = exe_info['path']
    genome_check = genome_preflight(genome_file)
    if not genome_check.get('ok'):
        return {'ok': False, 'error': 'genome preflight failed',
                'genome_check': genome_check,
                'hint': '先用一个真实的 FASTA/目录；genie 侧可用 bio_ref_genome / '
                        'bio_entrez_fetch 获取参考序列后再扫描'}

    if preflight_only:
        return {'ok': True, 'mode': 'preflight', 'backend': {'path': exe},
                'genome_check': genome_check,
                'interpretation_boundary': INTERPRETATION_BOUNDARY}

    if candidates:
        from editors import get_editor  # 同目录模块（脚本目录由 graft_ops 注入 sys.path）
        queries, derived_pattern = queries_from_candidates(candidates, editor)
        pattern = pattern or derived_pattern
        pam_side = get_editor(editor).pam_side   # seed 窗口方向随编辑器而定
    if not queries:
        raise ValueError('queries 或 candidates 至少给一个')
    pattern = pattern or 'N20NGG'

    selector, devices, device_note = pick_device(exe, device)
    if selector is None:
        return {'ok': False, 'error': 'no OpenCL device available',
                'devices': devices, 'device_note': device_note,
                'hint': '安装 OpenCL runtime（GPU 驱动自带；CPU 需 Intel/AMD OpenCL runtime）'}

    input_file = build_casoffinder_input(genome_file, pattern, queries, mismatches,
                                         workdir=workdir)
    tmp_out = output or os.path.join(workdir or graft_tmp_dir,
                                     f'casoffinder_out_{os.getpid()}.txt')
    os.makedirs(os.path.dirname(os.path.abspath(tmp_out)), exist_ok=True)

    attempts = []
    seen, tail = None, None
    for candidate in [selector] + [d['selector'] for d in devices
                                   if d.get('selector') and d['selector'] != selector][:2]:
        cmd = [exe, input_file, candidate, tmp_out]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                              encoding='utf-8', errors='replace')
        attempts.append({'device': candidate, 'rc': proc.returncode,
                         'stdout_tail': (proc.stdout or '')[-200:],
                         'stderr_tail': (proc.stderr or '')[-200:]})
        if proc.returncode == 0:
            seen, tail = candidate, proc
            break
        blob = ((proc.stdout or '') + (proc.stderr or '')).lower()
        if 'opencl' not in blob and 'device' not in blob:
            break  # 非设备问题，重试无意义
    if seen is None:
        return {'ok': False, 'error': f'cas-offinder failed on all attempted devices',
                'attempts': attempts, 'device_note': device_note,
                'input_file': input_file.replace('\\', '/'),
                'interpretation_boundary': INTERPRETATION_BOUNDARY}

    hits, truncated = _parse_hits(tmp_out, top_n)
    result = {
        'ok': True,
        'mode': 'scan',
        'backend': {'path': exe, 'source': exe_info.get('source')},
        # ── 批次 C 语义层：只给 observation，不给结论 ──────────────────────────
        'search_completeness': build_search_completeness(mismatch_searched=True),
        'assessment': build_assessment(),
        'per_guide': aggregate_per_guide(hits, queries, seed_length=seed_length,
                                         pam_side=pam_side),
        'search_parameters': {
            'genome_file': genome_file.replace('\\', '/'),
            'genome_size_bytes': genome_check.get('size_bytes'),
            'genome_records': genome_check.get('n_records'),
            'pattern': expand_pattern(pattern),
            'n_queries': len(queries),
            'mismatches': mismatches,
            'device': seen,
            'device_note': device_note,
            'bulge': 'unsupported（Cas-OFFinder 本体需独立包装脚本，本插件不静默忽略）',
        },
        'devices': devices,
        'genome_check': genome_check,
        'n_hits': len(hits),
        'hits': hits,
        'hits_truncated': truncated,
        'raw_hits_file': tmp_out.replace('\\', '/'),
        'input_file': input_file.replace('\\', '/'),
        'attempts': attempts,
        'interpretation_boundary': INTERPRETATION_BOUNDARY,
    }
    if not hits:
        result['zero_hit_warning'] = ZERO_HIT_WARNING
    if any(h['mismatches'] == 0 for h in hits):
        result['notes'] = [f"命中中含 {sum(1 for h in hits if h['mismatches'] == 0)} 条"
                           f"**完全匹配**位点（0 mismatch）——注意这可能包含设计靶点本身，"
                           f"解读时需按坐标与设计位点比对"]
    return result
