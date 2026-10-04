"""sequtil.py — 序列规范化与序列工具（graft 内单点实现）。

为什么单独成模块：guides.py 与将来的 base_edit.py / offtarget 预检都需要同一套清洗与
反向互补规则；graft 的硬教训是「同一个事实只能有一处实现」。

与 dsh-bio-genie 的 python/seq_util.py 是同族契约，但**不跨包 import**：两个插件是独立
npm 包，跨包 import 会把发布节奏与加载顺序绑死。
"""
from __future__ import annotations

import os

# IUPAC 互补表（含模糊碱基；无义字符原样保留，由调用方决定是否校验）
_COMPLEMENT = str.maketrans(
    'ACGTNRYKMSWBDHVUacgtnrykmswbdhvu',
    'TGCANYRMKSWVHDBAtgcanyrmkswvhdba',
)


def revcomp(seq: str) -> str:
    """反向互补（IUPAC 感知）。"""
    return seq.translate(_COMPLEMENT)[::-1]


def split_fasta(raw: str) -> list[tuple[str | None, str]]:
    """把（可能多条的）FASTA / 裸序列切成 [(record_id, sequence), ...]。

    record_id 对裸序列是 None；序列统一大写并去掉所有空白。
    """
    text = str(raw).replace('\r\n', '\n').replace('\r', '\n')
    records: list[tuple[str | None, str]] = []
    current_id: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        if chunks:
            seq = ''.join(''.join(chunks).split()).upper()
            if seq:
                records.append((current_id, seq))

    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('>'):
            flush()
            chunks = []
            header = stripped[1:].strip()
            current_id = header.split()[0] if header else None
            continue
        if stripped:
            chunks.append(stripped)
    flush()
    return records


# 序列输入解析：文件路径支持（2026-10-04，与 dsh-bio-genie 同族修复对齐）
# 背景：agent 会把 FASTA 文件路径直接传给 sequence 参数；修复前路径字符串被当序列
# 静默清洗（无 PAM → 0 候选），产出「无候选」的无声错误结果。
# 实现注记：本段刻意不含转义字面量（换行/回车/反斜杠用 chr 常量），
# 规避部分写入链路对「转义符 + 字母」序列的折损。
_LF = chr(10)
_CR = chr(13)
_BS = chr(92)
_SEQ_FILE_EXTS = ('.fasta', '.fa', '.fna', '.fas', '.ffn', '.faa', '.seq', '.txt')


def _looks_like_path(v: str) -> bool:
    """保守判定是否文件路径：序列字符集不含斜杠/反斜杠与点号扩展名模式。"""
    if len(v) >= 512 or _LF in v or _CR in v:
        return False
    if os.path.exists(v):
        return True
    if '/' in v or _BS in v:
        return True
    return v.lower().endswith(_SEQ_FILE_EXTS)


def resolve_sequence_input(raw):
    """若 raw 是（存在的）文件路径 → 读取文件文本；像路径但不存在 → 明确报错；否则原样返回。"""
    if not isinstance(raw, str):
        return raw
    v = raw.strip()
    if not v or not _looks_like_path(v):
        return raw
    if not os.path.exists(v):
        raise ValueError(
            f'sequence 看起来是文件路径但文件不存在：{v}'
            f'（相对路径基于当前工作目录；或直接传入序列 / FASTA 内容）')
    if os.path.isdir(v):
        raise ValueError(f'sequence 指向的是目录而不是文件：{v}')
    with open(v, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def clean_sequence(raw: str, *, record: int = 0) -> tuple[str, str | None, int]:
    """把 FASTA / 裸序列 / 多行序列统一成 (大写单串, record_id, n_records)。

    历史缺陷（2026-09-14 修复）：旧实现先 `''.join(sequence.split())` 去掉换行，再用
    `re.sub(r'^>[^\\n]*\\n?', ...)` 剥头行 —— 换行已不存在，`[^\\n]*` 贪婪匹配吃掉整条序列，
    于是**任何 FASTA 输入**都报 `empty sequence after cleaning`（实测复现，见
    test/golden-ops.mjs 的 D1 用例）。
    """
    if raw is None or not str(raw).strip():
        raise ValueError('sequence required (raw DNA or FASTA)')
    raw = resolve_sequence_input(raw)
    records = split_fasta(raw)
    if not records:
        raise ValueError('empty sequence after cleaning')
    if record < 0 or record >= len(records):
        raise IndexError(f'record index {record} out of range (n_records={len(records)})')
    seq, rid = records[record][1], records[record][0]
    return seq, rid, len(records)


def gc_content(seq: str) -> float:
    """GC 含量（空串返回 0.0）。"""
    if not seq:
        return 0.0
    s = seq.upper()
    return (s.count('G') + s.count('C')) / len(s)
