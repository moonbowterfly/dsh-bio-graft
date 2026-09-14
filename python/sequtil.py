"""sequtil.py — 序列规范化与序列工具（graft 内单点实现）。

为什么单独成模块：guides.py 与将来的 base_edit.py / offtarget 预检都需要同一套清洗与
反向互补规则；graft 的硬教训是「同一个事实只能有一处实现」。

与 dsh-bio-genie 的 python/seq_util.py 是同族契约，但**不跨包 import**：两个插件是独立
npm 包，跨包 import 会把发布节奏与加载顺序绑死。
"""
from __future__ import annotations

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


def clean_sequence(raw: str, *, record: int = 0) -> tuple[str, str | None, int]:
    """把 FASTA / 裸序列 / 多行序列统一成 (大写单串, record_id, n_records)。

    历史缺陷（2026-09-14 修复）：旧实现先 `''.join(sequence.split())` 去掉换行，再用
    `re.sub(r'^>[^\\n]*\\n?', ...)` 剥头行 —— 换行已不存在，`[^\\n]*` 贪婪匹配吃掉整条序列，
    于是**任何 FASTA 输入**都报 `empty sequence after cleaning`（实测复现，见
    test/golden-ops.mjs 的 D1 用例）。
    """
    if raw is None or not str(raw).strip():
        raise ValueError('sequence required (raw DNA or FASTA)')
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
