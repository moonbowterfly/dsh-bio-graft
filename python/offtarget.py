"""offtarget.py — Cas-OFFinder 后端（BSD-3 官方 Windows x86-64 二进制）。

搜索模式（Cas-OFFinder）：
  <patterns_file> <output_file> [mismatches [DNA/RNA bulge sizes]]
  patterns_file 格式：
      GGGTTTGGGG TTTAAG...   (PAM[, guide])
      N20NGG                 (PAM-only, 含 N 通配)
      turbo  /  LLVM 之类 GPU 选项看 binary 支持

graft 的后端定位（GPT 评审裁决采纳）：
  genie 侧可临时借用通用比对工具；但「CRISPR off-target 的语义解释」
  （PAM / mismatch / bulge / functional annotation / 风险分级）归 graft。
  本模块先做 **命令行包装 + 结果解析 + warning 生成**，不做"efficiency 预测"。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

CAS_OFFINDER_URL = ('https://github.com/snugel/cas-offinder/releases/download/'
                    '2.4.1/cas-offinder_windows_x86-64.zip')  # 稳定版 v2.4.1；注意 x86-64（非 x86_64）
graft_data_dir = os.path.expanduser('~/.dsh/dsh-bio-graft')
graft_bin_dir = os.path.join(graft_data_dir, 'bin')


def locate_casoffinder() -> dict:
    """定位 cas-offinder 可执行文件。探测顺序：
      1) `GRAFT_CAS_OFFINDER` env（用户显式指定，最高优先级）
      2) `~/.dsh/dsh-bio-graft/bin/cas-offinder.exe`（graft 自管 bin dir；
         `offtarget_backend ensure` 自动下载官方 BSD-3 二进制）
      3) PATH 的 `cas-offinder`
      4) `<graft python dir>/cas-offinder.exe`（手动放置）
    返回 {path, source, version, ok}；ok=false 时附 install_hint。
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
            '安装方法 A（自动）：agent 调 offtarget_backend op, action="ensure" 自动下载 '
            '官方 BSD-3 Windows 二进制到 ~/.dsh/dsh-bio-graft/bin/。'
            '方法 B（手动）：https://github.com/snugel/cas-offinder/releases 下载 '
            'cas-offinder_windows_x86-64.zip 解压后把 cas-offinder.exe 放到 '
            '~/.dsh/dsh-bio-graft/bin/，或用 GRAFT_CAS_OFFINDER 环境变量指向。'
        ),
        'license': 'BSD-3-Clause (原仓库 LICENSE)',
    }


def ensure_casoffinder() -> dict:
    """下载官方 Windows 二进制（v2.4.1，BSD-3）到 graft bin 目录。幂等。"""
    if os.path.exists(os.path.join(graft_bin_dir, 'cas-offinder.exe')):
        return {'ok': True, 'path': os.path.join(graft_bin_dir, 'cas-offinder.exe'),
                'note': 'already present'}
    os.makedirs(graft_bin_dir, exist_ok=True)
    zip_path = os.path.join(graft_bin_dir, 'cas-offinder_windows.zip')
    sys.stderr.write(f'[graft] downloading Cas-OFFinder v2.4.1 (BSD-3) ...\n')
    urllib.request.urlretrieve(CAS_OFFINDER_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        exe_target = None
        for n in zf.namelist():
            if n.endswith('cas-offinder.exe') or n.lower() == 'cas-offinder.exe':
                zf.extract(n, graft_bin_dir)
                exe_target = os.path.join(graft_bin_dir, n)
        if not exe_target:
            # 或许 zip 顶层解压即可
            zf.extractall(graft_bin_dir)
            exe_target = os.path.join(graft_bin_dir, 'cas-offinder.exe')
        if not os.path.exists(exe_target):
            raise RuntimeError('cas-offinder.exe not found in archive')
        if os.path.dirname(exe_target) != graft_bin_dir:
            os.replace(exe_target, os.path.join(graft_bin_dir, 'cas-offinder.exe'))
    os.remove(zip_path)
    exe = os.path.join(graft_bin_dir, 'cas-offinder.exe')
    # 冒烟
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    return {'ok': True, 'path': exe, 'version_probe_stdout_head': (r.stdout or r.stderr)[:200]}


def casoffinder_scan(pattern_file: str, genome_file: str, mismatches: int = 3,
                     rna_bulge: int = 0, dna_bulge: int = 0,
                     output=None, top_n: int = 200) -> dict:
    """Cas-OFFinder 扫描：需要 graft 所用 pattern file 与（用户的）参考基因组 FASTA。

    pattern_file 是 Cas-OFFinder 原生格式：
        N20NGG                     [单 PAM-only 模式]（也可带空格 guide 限定）
        GGGTTTGGGG NNNNNNNNNNNNRNNN   （PAM + optional fallback）
    genome_file 是（拼接好的）多 FASTA 或 .fa genome；graft 不代用户准备 genome。
    """
    exe_info = locate_casoffinder()
    if not exe_info.get('ok'):
        return {'ok': False, 'error': 'cas-offinder not found',
                **exe_info}
    exe = exe_info['path']
    if not os.path.exists(pattern_file):
        raise FileNotFoundError(pattern_file)
    if not os.path.exists(genome_file):
        raise FileNotFoundError(genome_file)
    tmp_out = output or os.path.join(tempfile.gettempdir(), f'graft_off_{os.getpid()}.txt')
    if output is None:
        os.makedirs(os.path.dirname(tmp_out), exist_ok=True)
    cmd = [exe, pattern_file, genome_file, str(mismatches),
           f'{dna_bulge},{rna_bulge}', tmp_out]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        return {'ok': False, 'error': f'cas-offinder exit {p.returncode}',
                'stderr': p.stderr[-500:], 'cmd': ' '.join(cmd)}
    hits = []
    with open(tmp_out, encoding='utf-8') as f:
        header = f.readline().strip()      # "Bulge type DNA RNA Chromosome Position ..."
        for i, line in enumerate(f):
            if i >= top_n:
                hits.append({'note': 'truncated at top_n'})
                break
            hits.append(line.strip().split('\t'))
    return {
        'ok': True,
        'backend': {'path': exe, 'source': exe_info.get('source')},
        'pattern_file': pattern_file,
        'genome_file': genome_file,
        'mismatches': mismatches, 'dna_bulge': dna_bulge, 'rna_bulge': rna_bulge,
        'raw_lines': hits,
        'semantics': ('Cas-OFFinder 原始输出未做 CRISPR 语义解释；'
                      'graft 后续版本做 PAM/mismatch 分栏与功能注释'),
    }
