"""guide_contract.py — 候选身份契约（GF-1）与最小 GenomeContext 坐标核验（GF-2）。

GF-1：guide_id 由「规范化模板序列身份 + 编辑器 + PAM/spacer + 局部坐标 + strand」
      确定性派生（候选重排不改身份；同 spacer 不同位点各自存在）。评分/排名以
      guide_id 为无歧义身份，protospacer 仅作展示兼容。身份篡改/冲突 → 响亮失败。
GF-2：GenomeContext 区分 local/genomic 两模式；genomic 坐标映射（正反向）与参考核验
      独立实现，不用 caller 传入的 hash 代替实际比对；无实际参考核对只能标 unverified。
"""
from __future__ import annotations

import hashlib
import json

GUIDE_IDENTITY_SCHEMA = "graft.guide_identity.v1"
GENOME_CONTEXT_SCHEMA = "graft.genome_context.v1"


def template_seq_hash(seq: str) -> str:
    """规范化模板序列 hash（大写 + 去空白）——输入身份由实际解析计算，不信任标签。"""
    normalized = "".join(str(seq).upper().split())
    return "sha256:" + hashlib.sha256(normalized.encode("ascii")).hexdigest()


def _canon(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_identity(candidate: dict, template_hash: str | None = None) -> dict:
    """从候选内容构建 identity_schema（不信任候选已有的 guide_id/identity 字段）。"""
    th = (template_hash or candidate.get("_template_seq_hash") or candidate.get("template_seq_hash")
          or (candidate.get("identity_schema") or {}).get("template_seq_hash"))
    identity = {
        "schema": GUIDE_IDENTITY_SCHEMA,
        "template_seq_hash": th,
        "editor": candidate.get("editor") or candidate.get("_editor"),
        "pam_pattern": candidate.get("pam_pattern") or candidate.get("_pam_pattern"),
        "protospacer": (candidate.get("protospacer") or "").upper() if candidate.get("protospacer") else None,
        "pam": (candidate.get("pam") or "").upper() if candidate.get("pam") else None,
        "start_0": candidate.get("start_0"),
        "end_0": candidate.get("end_0"),
        "strand": candidate.get("strand", "+"),
    }
    # 有实际核验的 genomic context 时才纳入位点身份（GF-2）
    gc = candidate.get("genome_context") or candidate.get("_genome_context")
    if isinstance(gc, dict) and gc.get("mode") == "genomic" and gc.get("reference_verification", {}).get("status") == "verified":
        identity["genomic_locus"] = {
            "record_seq_hash": gc["reference_verification"].get("record_seq_hash"),
            "contig": gc.get("contig"),
            "region": [gc.get("region_start_0"), gc.get("region_end_0")],
            "input_strand_relative_to_reference": gc.get("input_strand_relative_to_reference"),
        }
    return identity


def guide_id_for(identity: dict) -> str:
    """identity → 稳定 guide_id（sha256 前缀）。"""
    return "sha256:" + hashlib.sha256(_canon(identity).encode("utf-8")).hexdigest()[:32]


def assign_guide_identity(candidate: dict, template_hash: str | None = None,
                          editor: str | None = None, pam_pattern: str | None = None) -> dict:
    """给候选填 guide_id + identity_schema。

    - 已有 guide_id/identity_schema → 做一致性核对；篡改/冲突 → 抛 ValueError。
    - 无 → 由候选内容确定性派生（重排不变）。
    返回（原地不修改输入的）含身份的新 dict？——为无副作用，复制后返回。
    """
    out = dict(candidate)
    out.setdefault("editor", editor)
    out.setdefault("pam_pattern", pam_pattern)
    th = template_hash or candidate.get("_template_seq_hash")
    identity = build_identity(out, template_hash=th)
    gid = guide_id_for(identity)

    existing_gid = out.get("guide_id")
    existing_ident = out.get("identity_schema")
    if existing_gid or existing_ident:
        # 一致性核对：已有身份必须与内容一致
        if existing_ident:
            if existing_ident.get("schema") != GUIDE_IDENTITY_SCHEMA:
                raise ValueError("identity_schema.schema 不匹配（未知身份契约）")
            recomputed = guide_id_for(existing_ident)
            if existing_gid and existing_gid != recomputed:
                raise ValueError(
                    f"guide_id 与 identity_schema 不一致（身份篡改）："
                    f"guide_id={existing_gid} identity→{recomputed}")
            # 只要候选有对应实际字段，就必须与声明的完整身份一致。
            # 模板序列不随候选传递时沿用已有 hash；策略入口另核对实际 sequence。
            if existing_ident != identity:
                raise ValueError("候选内容与 identity_schema 冲突（身份篡改）")
            # 保留既有身份（不重建，避免丢失 template_seq_hash 等已核验上下文）
            out["guide_id"] = existing_gid or recomputed
            out["identity_schema"] = existing_ident
            return out
        # 有 guide_id 无 identity_schema：以内容派生并核对
        if existing_gid and existing_gid != gid:
            raise ValueError(
                f"guide_id 与候选内容不一致（身份篡改）：guide_id={existing_gid} 内容→{gid}")
    out["guide_id"] = gid
    out["identity_schema"] = identity
    return out


# ──────────────────────────────────────────────────────────────────────────
# GF-2：GenomeContext 与坐标核验
# ──────────────────────────────────────────────────────────────────────────

def validate_genome_context(gc: dict | None) -> dict:
    """归一化/校验 GenomeContext。None → local 模式。

    提供不完整 genomic 字段时失败（不假定起点 0、正链、默认 assembly）。
    返回归一化 context；非法 → 抛 ValueError。"""
    if gc is None:
        return {"mode": "local"}
    if not isinstance(gc, dict):
        raise ValueError("genome_context 必须是对象")
    mode = gc.get("mode", "local")
    if mode == "local":
        return {"mode": "local"}
    if mode != "genomic":
        raise ValueError(f"未知 genome_context.mode {mode!r}（local|genomic）")

    required = ("assembly_accession", "contig", "region_start_0", "region_end_0",
                "input_strand_relative_to_reference", "input_sequence_length",
                "input_sequence_hash")
    missing = [k for k in required if gc.get(k) is None]
    if missing:
        raise ValueError(
            f"genomic 模式缺少必需字段 {missing}——不假定起点 0/正链/默认 assembly")
    for key in ("assembly_accession", "contig"):
        if not isinstance(gc[key], str) or not gc[key].strip():
            raise ValueError(f"genome_context.{key} 必须是非空字符串")
    for key in ("region_start_0", "region_end_0", "input_sequence_length"):
        if isinstance(gc[key], bool) or not isinstance(gc[key], int):
            raise ValueError(f"genome_context.{key} 必须是整数")
    a, b = gc["region_start_0"], gc["region_end_0"]
    if a < 0 or b <= a:
        raise ValueError(f"region [start_0,end_0) 非法：[{a},{b})")
    strand = gc["input_strand_relative_to_reference"]
    if strand not in ("+", "-"):
        raise ValueError(f"input_strand_relative_to_reference 必须是 + 或 -，收到 {strand!r}")
    length = gc["input_sequence_length"]
    if length <= 0:
        raise ValueError("input_sequence_length 必须 > 0")
    if length != (b - a):
        raise ValueError(
            f"input_sequence_length={length} 与 region 长度 {b - a} 不一致")
    ver = gc.get("reference_verification") or {}
    out = dict(gc)
    out["mode"] = "genomic"
    out["region_start_0"] = a
    out["region_end_0"] = b
    out["input_strand_relative_to_reference"] = strand
    out["input_sequence_length"] = length
    out["reference_verification"] = {"status": "unverified",
                                      "note": "caller 核验声明不构成实际核验"}
    if ver:
        out["caller_reference_verification_claim"] = ver
    out["assembly_accession_provenance"] = "caller_declared"
    return out


def _flip(strand: str) -> str:
    return "-" if strand == "+" else "+"


def genomic_strand_of(local_strand: str, region_strand: str) -> str:
    """局部 guide strand + region 方向 → genomic strand。"""
    return local_strand if region_strand == "+" else _flip(local_strand)


def map_to_genomic(start_0: int, end_0: int, cut_site_0: int | None,
                   genome_context: dict) -> dict:
    """把局部（输入序列 frame）坐标映射到 genomic 坐标。

    正向 region [a,b)：[s,e)→[a+s,a+e)，cut k→a+k。
    反向 region [a,b)：[s,e)→[b-e,b-s)，cut k→b-k（切点不套用碱基索引的 -1）。"""
    a = genome_context["region_start_0"]
    b = genome_context["region_end_0"]
    size = b - a
    if not (0 <= start_0 <= end_0 <= size):
        raise ValueError("guide 区间超出 genome_context region")
    if cut_site_0 is not None and not (0 <= cut_site_0 <= size):
        raise ValueError("cut_site_0 超出 genome_context region 边界")
    strand = genome_context["input_strand_relative_to_reference"]
    if strand == "+":
        gs, ge = a + start_0, a + end_0
        gk = (a + cut_site_0) if cut_site_0 is not None else None
    else:
        gs, ge = b - end_0, b - start_0
        gk = (b - cut_site_0) if cut_site_0 is not None else None
    return {
        "genomic_start_0": gs,
        "genomic_end_0": ge,
        "genomic_cut_site_0": gk,
    }


def verify_reference_region(reference_fasta: str | None, genome_context: dict,
                            input_sequence: str | None = None,
                            reference_seq: str | None = None) -> dict:
    """读取参考 FASTA，计算文件字节 hash 与 record 规范化序列 hash，实际比对区段。

    reference_seq：若调用方已解析出参考序列（避免重复读大文件）可传入；
    否则从 reference_fasta 读取（单 record 或按 contig 匹配）。
    返回参考核验结果 dict；未提供参考 → 标 unverified（不用 caller hash 冒充）。"""
    if not reference_fasta and reference_seq is None:
        return {"status": "unverified",
                "note": "无参考 FASTA / 参考序列，无法实际核验（不信任 caller 传入的 hash）"}

    file_byte_hash = None
    contig_seq = None
    if reference_seq is not None:
        contig_seq = "".join(str(reference_seq).upper().split())
    else:
        raw = open(reference_fasta, "rb").read()
        file_byte_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        # 解析单/多 record；按 contig 匹配 header
        text = raw.decode("utf-8", errors="replace")
        records = {}
        cur_id, chunks = None, []
        for line in text.splitlines():
            if line.startswith(">"):
                if cur_id is not None:
                    records[cur_id] = "".join(chunks).upper()
                header = line[1:].strip()
                if not header:
                    raise ValueError("参考 FASTA record ID 为空")
                cur_id = header.split()[0]
                if cur_id in records:
                    raise ValueError(f"参考 FASTA 重复 record ID: {cur_id}")
                chunks = []
            elif cur_id is not None:
                chunks.append("".join(line.split()))
        if cur_id is not None:
            records[cur_id] = "".join(chunks).upper()
        if not records:
            raise ValueError("参考 FASTA 无 record")
        if genome_context.get("contig") not in records:
            raise ValueError(f"参考 FASTA 中未找到 contig {genome_context.get('contig')}; "
                             f"可用 ID: {sorted(records)[:5]}")
        contig_seq = records[genome_context["contig"]]

    record_hash = "sha256:" + hashlib.sha256(contig_seq.encode("ascii")).hexdigest()
    a, b = genome_context["region_start_0"], genome_context["region_end_0"]
    if b > len(contig_seq):
        return {"status": "unverified",
                "note": f"region [{a},{b}) 超出参考 contig 长度 {len(contig_seq)}",
                "file_byte_hash": file_byte_hash, "record_seq_hash": record_hash}

    region = contig_seq[a:b]
    result = {"file_byte_hash": file_byte_hash, "record_seq_hash": record_hash,
              "contig_length": len(contig_seq)}
    if input_sequence is None:
        return {"status": "unverified",
                "note": "未提供输入序列，无法做区段比对（只记录参考 hash）", **result}

    input_norm = "".join(str(input_sequence).upper().split())
    comp = str.maketrans("ACGTN", "TGCAN")
    region_rc = region.translate(comp)[::-1]
    region_strand = genome_context["input_strand_relative_to_reference"]
    if region_strand == "+" and input_norm == region:
        result["status"] = "verified"
        result["note"] = "输入序列 = 参考 region 正向片段"
    elif region_strand == "-" and input_norm == region_rc:
        result["status"] = "verified"
        result["note"] = "输入序列 = 参考 region 反向互补片段"
    else:
        result["status"] = "mismatch"
        result["note"] = (f"输入序列与参考 region[{region_strand}] 片段不一致"
                          f"（caller 声明的 input_sequence_hash 不代替实际比对）")
    return result
