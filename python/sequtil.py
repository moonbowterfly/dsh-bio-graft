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


# ── GF-3：翻译后果（连续完整 CDS、phase0、标准遗传密码、正反链）───────────────
STANDARD_GENETIC_CODE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def translate_cds(seq: str, phase: int = 0, genetic_code: dict | None = None) -> str:
    """翻译一段完整 CDS 序列 → 氨基酸串（* 表示终止）。

    phase 必须为 0（一期仅支持 phase0）。返回从 phase 起、按完整密码子翻译的 aa 串
    （不足 3 的尾部不译）。"""
    if phase != 0:
        raise ValueError("一期仅支持 phase=0（连续完整 CDS）；非零 phase 不猜测")
    if genetic_code not in (None, 'standard', 1):
        raise ValueError('一期仅支持标准遗传密码')
    code = STANDARD_GENETIC_CODE
    s = "".join(str(seq).upper().split())
    aa = []
    for i in range(0, len(s) - 2, 3):
        codon = s[i:i + 3]
        if len(codon) < 3:
            break
        aa.append(code.get(codon, "X"))
    return "".join(aa)


def simulate_deletion_translation(full_seq, del_start, del_end,
                                  cds_start, cds_end, cds_strand="+",
                                  phase=0, genetic_code=None, cds_complete=True,
                                  cds_exon_count=1):
    """模拟删除并重新提取/翻译完整 CDS（GF-3）。

    全部坐标 0-based 半开区间，属于**原始输入序列 frame**（非 genomic、非删除后）。
    返回 dict；不满足完整 CDS 前提时返回 {"translation_computed": False, ...}。
    """
    seq, _, n_records = clean_sequence(full_seq)
    if n_records != 1:
        raise ValueError('sequence 必须仅包含一条原始输入序列')
    out = {
        "deletion_interval_0based_half_open": [del_start, del_end],
        "deletion_size_bp": del_end - del_start,
        "cds_0based_half_open": [cds_start, cds_end],
        "cds_strand": cds_strand,
        "phase": phase,
        "genetic_code": "standard" if genetic_code in (None, 'standard', 1) else str(genetic_code),
        "method_id": "graft.cds_deletion_translation",
        "method_version": 2,
        "simulated_sequence_hash": None,
    }
    if (phase != 0 or genetic_code not in (None, 'standard', 1) or
            cds_complete is not True or cds_exon_count != 1 or cds_strand not in ('+', '-')):
        return {**out, "translation_computed": False, "translation_status": "not_supported",
                "applicability_note": "仅支持完整、单外显子、phase0、标准遗传密码的正反链 CDS"}
    if cds_end is None or cds_end <= cds_start:
        out["translation_computed"] = False
        out["translation_status"] = "not_evaluated"
        out["applicability_note"] = "未提供完整 CDS 终点——不计算翻译（in_frame 仅保留几何 %3）"
        return out
    if del_end > len(seq) or del_start < 0 or del_end < del_start:
        raise ValueError(f"删除区间非法：[{del_start},{del_end})（序列长 {len(seq)}）")
    if cds_end > len(seq) or cds_start < 0:
        raise ValueError(f"CDS 越界：[{cds_start},{cds_end})（序列长 {len(seq)}）")
    if (cds_end - cds_start) % 3 != 0:
        return {**out, "translation_computed": False, "translation_status": "not_supported",
                "applicability_note": "原完整 CDS 长度不是 3 的整数倍"}
    if not isinstance(del_start, int) or not isinstance(del_end, int):
        raise ValueError('删除区间必须是整数坐标')
    if del_start < cds_start < del_end or del_start < cds_end < del_end:
        return {**out, "translation_computed": False, "translation_status": "not_supported",
                "applicability_note": "删除跨越 CDS 起点或终点"}

    deleted_seq = seq[:del_start] + seq[del_end:]
    deletion_size = del_end - del_start
    if del_end <= cds_start:
        new_start, new_end, removed, relation = (cds_start - deletion_size,
                                                  cds_end - deletion_size, 0, 'upstream')
    elif del_start >= cds_end:
        new_start, new_end, removed, relation = cds_start, cds_end, 0, 'downstream'
    else:
        new_start, new_end, removed, relation = (cds_start, cds_end - deletion_size,
                                                  deletion_size, 'within_cds')
    coding_seq = deleted_seq[new_start:new_end]
    if cds_strand == "-":
        coding_seq = revcomp(coding_seq)
    out["simulated_sequence_hash"] = "sha256:" + __import__("hashlib").sha256(
        coding_seq.encode("ascii")).hexdigest()
    out["removed_from_cds_bp"] = removed
    out["deletion_relation_to_cds"] = relation
    out["simulated_cds_interval_0based_half_open"] = [new_start, new_end]
    out["simulated_full_sequence_hash"] = "sha256:" + __import__('hashlib').sha256(
        deleted_seq.encode('ascii')).hexdigest()

    aa = translate_cds(coding_seq, phase=phase, genetic_code=genetic_code)
    stop_positions = [i for i, a in enumerate(aa) if a == "*"]
    frame_preserved = (removed % 3 == 0)
    internal_stops = [p for p in stop_positions if p != len(aa) - 1] if aa else []
    premature = bool(internal_stops)
    protein_length = (stop_positions[0] if stop_positions else len(aa))
    out.update({
        "translation_computed": True,
        "simulated_cds_length_bp": len(coding_seq),
        "frame_preserved_by_length": deletion_size % 3 == 0,
        "cds_frame_preserved": frame_preserved,
        "trailing_incomplete_codon_bp": len(coding_seq) % 3,
        "premature_stop_detected": premature,
        "protein_length_aa": protein_length,
        "terminal_stop": bool(frame_preserved and stop_positions and stop_positions[-1] == len(aa) - 1),
        "internal_stop_positions": internal_stops,
        "translated_prefix": aa[:60],
        "translation_validation": {
            "status": "computed" if frame_preserved else "frameshift_partial_translation",
            "note": ("frame_preserved_by_length 只回答长度是否 %3==0；"
                     "蛋白完整/功能保持以 premature_stop_detected 与 protein_length 为准，"
                     "不能由长度 %3 单独声明"),
        },
    })
    out["translation_status"] = out["translation_validation"]["status"]
    return out
