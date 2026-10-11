# test_gf_contract.py — GF-1/GF-2/GF-3 定向测试（graft）
# 运行：<python> -I test/test_gf_contract.py（纯标准库）
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

from guides import enumerate_guides, score_guides
from rank import rank_candidates
from strategy import evaluate_strategy
from sequtil import translate_cds, simulate_deletion_translation, revcomp
from guide_contract import (assign_guide_identity, guide_id_for, build_identity,
                            template_seq_hash, validate_genome_context, map_to_genomic,
                            genomic_strand_of, verify_reference_region)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ── GF-1 ──────────────────────────────────────────────────────────────────
print("[GF-1.1] guide_id 确定性：候选重排不改身份；同 spacer 不同位点各自存在")
seq = "ATGCGTACGTTTTCGTTTAGGGCGTTTAGGTTTAGGGCCCATGCGTACGTTT"
res = enumerate_guides(seq, editor="SpCas9")
cands = res["candidates"]
check("有候选", len(cands) > 0, f"n={len(cands)}")
check("每条候选有 guide_id", all(c.get("guide_id") for c in cands))
check("每条候选有 identity_schema", all(c.get("identity_schema") for c in cands))
ids_orig = [c["guide_id"] for c in cands]
reordered = sorted(cands, key=lambda c: -c["start_0"])
res2 = enumerate_guides(seq, editor="SpCas9")
ids2 = [c["guide_id"] for c in res2["candidates"]]
check("重排不改 guide_id（同输入同顺序内容）", ids_orig == ids2)

# 同 spacer 不同位点：构造两条仅 start_0 不同的候选 → 不同 guide_id
if len(cands) >= 2:
    a, b = cands[0], cands[1]
    if a["protospacer"] == b["protospacer"] and a["start_0"] != b["start_0"]:
        check("同 spacer 不同位点 → guide_id 不同", a["guide_id"] != b["guide_id"],
              f"{a['guide_id']} vs {b['guide_id']}")
    else:
        # 手工构造两条「同 spacer 不同位点」的候选（去掉已有身份，重新派生）
        def fresh(c, s):
            d = dict(c)
            d.pop("guide_id", None); d.pop("identity_schema", None)
            d["start_0"] = s; d["end_0"] = s + 23
            return d
        c1 = fresh(a, 100); c2 = fresh(a, 200)
        i1 = assign_guide_identity(c1, template_hash=res["template_seq_hash"], editor="SpCas9", pam_pattern="NGG")
        i2 = assign_guide_identity(c2, template_hash=res["template_seq_hash"], editor="SpCas9", pam_pattern="NGG")
        check("同 spacer 不同位点 → guide_id 不同（手工）", i1["guide_id"] != i2["guide_id"],
              f"{i1['guide_id']} vs {i2['guide_id']}")

print("[GF-1.2] 身份篡改 → 响亮失败")
c = dict(cands[0])
c["guide_id"] = "sha256:deadbeef000000000000000000000000"
try:
    assign_guide_identity(c, template_hash=res["template_seq_hash"], editor="SpCas9", pam_pattern="NGG")
    check("篡改 guide_id 报错", False, "未报错")
except ValueError as e:
    check("篡改 guide_id 报错", True, str(e)[:60])

print("[GF-1.3] 身份与内容冲突 → 失败")
c = dict(cands[0])
c["protospacer"] = "T" + c["protospacer"][1:]  # 改 spacer 但保留原 identity
try:
    assign_guide_identity(c, template_hash=res["template_seq_hash"], editor="SpCas9", pam_pattern="NGG")
    check("identity 与内容冲突报错", False, "未报错")
except ValueError:
    check("identity 与内容冲突报错", True)

print("[GF-1.4] 评分深复制：保留 template_hits/cut_site_0/自定义注释；不原地改输入")
c0 = dict(cands[0])
c0["custom_annotation"] = {"note": "keep me"}
c0["offtarget_summary"] = {"total": 3}
orig_keys = set(c0.keys())
scored = score_guides([c0], editor="SpCas9")["candidates"][0]
check("保留 template_hits", "template_hits" in scored)
check("保留 cut_site_0", "cut_site_0" in scored)
check("保留 custom_annotation", scored.get("custom_annotation") == {"note": "keep me"})
check("保留 offtarget_summary", scored.get("offtarget_summary") == {"total": 3})
check("输入未被原地修改（无 on_target_scores）", "on_target_scores" not in c0)
check("输出含 on_target_scores", "on_target_scores" in scored)
check("guide_id 保留", scored.get("guide_id") == c0.get("guide_id"))

print("[GF-1.5] 评分幂等：重复评分 warnings 不累积、结果一致")
s1 = score_guides([cands[0]], editor="SpCas9")["candidates"][0]
s2 = score_guides([s1], editor="SpCas9")["candidates"][0]
check("warnings 幂等（不重复追加）", s2.get("warnings") == s1.get("warnings"),
      f"{s2.get('warnings')} vs {s1.get('warnings')}")
check("on_target_scores 一致", s2["on_target_scores"] == s1["on_target_scores"])

print("[GF-1.6] 裸字符串 / 旧对象（无 guide_id）兼容")
s = score_guides(["ATGCGTACGT"], editor="SpCas9")["candidates"]
check("裸字符串可评分", len(s) == 1 and "gc_content" in s[0]["on_target_scores"])

print("[GF-1.7] rank：2 候选 → 0 排名反例（缺 ranking metric 时 fail-closed）")
# 两条候选都没有 on_target_scores（缺 ranking 度量）→ 用 weighted 要求缺失的度量
two = [
    {"protospacer": "AAAAACCCCGGGG", "start_0": 0, "end_0": 23, "strand": "+"},
    {"protospacer": "GGGGGTTTTTAAAA", "start_0": 5, "end_0": 28, "strand": "+"},
]
r = rank_candidates(two, policy="weighted", weights={"gc_content": 1.0})
check("2 候选全部排除 → n_ranked=0", r["n_ranked"] == 0, f"n_ranked={r['n_ranked']} n_excluded={r['n_excluded']}")
check("旧候选排除项带无歧义 record_key，身份仍 unresolved",
      len({e.get("record_key") for e in r["excluded"]}) == 2 and
      all(e.get("guide_id") is None for e in r["excluded"]))

print("[GF-1.8] rank 完整候选保留 + dominated_by 用 guide_id")
scored_two = score_guides([
    {"protospacer": "GCCCGGGAAACCC", "start_0": 0, "end_0": 23, "strand": "+",
     "template_hits": 1, "cut_site_0": 17, "_template_seq_hash": template_seq_hash("GCCCGGGAAACCCGAAAACCCGGGTT")},
    {"protospacer": "GAAAACCCGGGTT", "start_0": 10, "end_0": 33, "strand": "+",
     "template_hits": 2, "cut_site_0": 27, "_template_seq_hash": template_seq_hash("GCCCGGGAAACCCGAAAACCCGGGTT")},
], editor="SpCas9")["candidates"]
rp = rank_candidates(scored_two, policy="pareto", objectives=["template_hits:min", "gc_abs_dev:min"])
check("ranked 条目保留完整候选（含 cut_site_0）",
      all("cut_site_0" in e for e in rp["ranked"]), f"n_ranked={rp['n_ranked']}")
check("ranked 条目有 guide_id", all(e.get("guide_id") for e in rp["ranked"]))
check("dominated_by 用 guide_id（非 protospacer）",
      all(isinstance(d, str) and d.startswith("sha256:") for e in rp["ranked"] for d in e.get("dominated_by", [])))

# ── GF-2 ──────────────────────────────────────────────────────────────────
print("[GF-2.1] 正向 region 坐标映射")
gc_f = {"mode": "genomic", "assembly_accession": "NC_000913.3", "contig": "chr",
        "region_start_0": 100, "region_end_0": 400, "input_strand_relative_to_reference": "+",
        "input_sequence_length": 300, "input_sequence_hash": "x"}
gc_f = validate_genome_context(gc_f)
m = map_to_genomic(10, 30, 17, gc_f)
check("正向 [s,e)->[a+s,a+e)", m["genomic_start_0"] == 110 and m["genomic_end_0"] == 130, m)
check("正向 cut k -> a+k", m["genomic_cut_site_0"] == 117, m)

print("[GF-2.2] 反向 region 坐标映射（不套用 -1）")
gc_r = {"mode": "genomic", "assembly_accession": "NC_000913.3", "contig": "chr",
        "region_start_0": 100, "region_end_0": 400, "input_strand_relative_to_reference": "-",
        "input_sequence_length": 300, "input_sequence_hash": "x"}
gc_r = validate_genome_context(gc_r)
mr = map_to_genomic(10, 30, 17, gc_r)
check("反向 [s,e)->[b-e,b-s)", mr["genomic_start_0"] == 370 and mr["genomic_end_0"] == 390, mr)
check("反向 cut k -> b-k（不 -1）", mr["genomic_cut_site_0"] == 383, mr)

print("[GF-2.3] genomic strand 组合")
check("region+ local+ -> genomic+", genomic_strand_of("+", "+") == "+")
check("region- local+ -> genomic-", genomic_strand_of("+", "-") == "-")
check("region- local- -> genomic+", genomic_strand_of("-", "-") == "+")

print("[GF-2.4] 不完整 genomic 字段 → 失败")
try:
    validate_genome_context({"mode": "genomic", "assembly_accession": "X"})
    check("缺必需字段报错", False, "未报错")
except ValueError:
    check("缺必需字段报错", True)

print("[GF-2.5] 参考核验：文件字节 hash vs 记录规范化序列 hash 不同；实际比对区段")
import tempfile, hashlib
tmp = tempfile.mkdtemp(prefix="gf2-")
fasta = os.path.join(tmp, "ref.fa")
ref_seq = "A" * 400
with open(fasta, "w") as f:
    f.write(">chr description\n")
    f.write("A" * 80 + "\n")   # 换行
    f.write("A" * 80 + "\n")
    f.write("A" * 80 + "\n")
    f.write("A" * 80 + "\n")
    f.write("A" * 80 + "\n")   # 400 bp，80/行
vr = verify_reference_region(fasta, gc_f, input_sequence="A" * 300)
check("正向区段 verified", vr["status"] == "verified", vr)
check("file_byte_hash 存在", bool(vr.get("file_byte_hash")))
check("record_seq_hash 存在", bool(vr.get("record_seq_hash")))
check("字节 hash ≠ 序列 hash（FASTA 换行/头导致）",
      vr["file_byte_hash"] != vr["record_seq_hash"],
      f"{vr['file_byte_hash']} vs {vr['record_seq_hash']}")
vr2 = verify_reference_region(fasta, gc_r, input_sequence=revcomp("A" * 300))
check("反向区段（revcomp）verified", vr2["status"] == "verified", vr2)
vr3 = verify_reference_region(fasta, gc_f, input_sequence="C" * 300)
check("不匹配 -> mismatch", vr3["status"] == "mismatch", vr3)
vr4 = verify_reference_region(None, gc_f, input_sequence="A" * 300)
check("无参考 -> unverified（不信任 caller hash）", vr4["status"] == "unverified", vr4)

print("[GF-2.6] enumerate 带 genome_context 产生 genomic_* 字段（不改原坐标）")
gc2 = {"mode": "genomic", "assembly_accession": "NC_000913.3", "contig": "chr",
       "region_start_0": 0, "region_end_0": len(seq), "input_strand_relative_to_reference": "+",
       "input_sequence_length": len(seq), "input_sequence_hash": template_seq_hash(seq)}
resg = enumerate_guides(seq, editor="SpCas9", genome_context=gc2)
check("候选含 genomic_start_0", all("genomic_start_0" in c for c in resg["candidates"]))
check("候选含 genomic_strand", all("genomic_strand" in c for c in resg["candidates"]))
check("原局部 start_0 语义不变（region 从 0 起 → genomic==local 正向）",
      resg["candidates"][0]["genomic_start_0"] == resg["candidates"][0]["start_0"])

print("[GF-2.7] Cas12a（5' PAM）坐标映射")
res12 = enumerate_guides(seq, editor="Cas12a")
check("Cas12a 有候选", len(res12["candidates"]) > 0, f"n={len(res12['candidates'])}")

# ── GF-3 ──────────────────────────────────────────────────────────────────
print("[GF-3.1] ATGTCCGAATAA（MSE*）删除[4,7) → ATGTAATAA（M**）提前终止")
r = simulate_deletion_translation("ATGTCCGAATAA", 4, 7, 0, 12, cds_strand="+")
check("frame_preserved_by_length=True", r["frame_preserved_by_length"] is True, r)
check("premature_stop_detected=True", r["premature_stop_detected"] is True, r)
check("protein_length=1", r["protein_length_aa"] == 1, f"len={r['protein_length_aa']}")
check("翻译前缀 M**", r["translated_prefix"].startswith("M*"), r["translated_prefix"])

print("[GF-3.2] 无删除（完整 CDS）→ 正常翻译，terminal stop 合法")
r2 = simulate_deletion_translation("ATGTCCGAATAA", 12, 12, 0, 12, cds_strand="+")
check("完整 CDS premature=False", r2["premature_stop_detected"] is False, r2)
check("terminal_stop=True", r2["terminal_stop"] is True, r2)
check("蛋白长 3", r2["protein_length_aa"] == 3, r2["protein_length_aa"])

print("[GF-3.3] 反链镜像删除")
# 正链 CDS 是 ATG...；构造反链 CDS，删除区间镜像 [4,7) -> [5,8)。
fwd_cds = "ATGTCCGAATAA"
r3 = simulate_deletion_translation(revcomp(fwd_cds), 5, 8, 0, 12, cds_strand="-")
check("反链实际 CDS/镜像区间得到相同 M** 且提前终止",
      r3["translated_prefix"] == r["translated_prefix"] and
      r3["premature_stop_detected"] is True, r3)

print("[GF-3.4] 仅旧 CDS 起点 → 几何 %3 + 翻译未计算")
# 通过 strategy 的 in_frame 保留几何；simulate 层只给起点不给终点 → 不计算
r4 = simulate_deletion_translation("ATGTCCGAATAA", 4, 7, 0, None, cds_strand="+")
check("translation_computed=False", r4["translation_computed"] is False, r4)

print("[GF-3.5] CDS 越界 → 报错")
try:
    simulate_deletion_translation("ATGTCCGAATAA", 4, 7, 0, 99, cds_strand="+")
    check("CDS 越界报错", False, "未报错")
except ValueError:
    check("CDS 越界报错", True)

print("[GF-3.6] 跨模板配对禁止（strategy 层）")
seq_a = "ATGCGTACGTTTTCGTTTAGGGCGTTTAGGTTTAGGGCCCATGCGTACGTTT"
seq_b = "GGGGGCCCCCTTTTTAAAACCCCGGGGTTTTTAAAAACCCCGGGGTTTTTAA"
ca = enumerate_guides(seq_a, editor="SpCas9")["candidates"]
cb = enumerate_guides(seq_b, editor="SpCas9")["candidates"]
res_eval = evaluate_strategy(ca[:2] + cb[:2], strategy="deletion_pair",
                             sequence=seq_a, cds_start_0=0, cds_end_0=12)
check("跨模板对（cb 对）被拒", res_eval["n_pairs_rejected_template_identity"] >= 3,
      f"rejected={res_eval['n_pairs_rejected_template_identity']}")

print("[GF-3.7] 真实 lacZ：删除 [19,133) 无内部终止、986 aa（历史锚点，独立实算）")
lacZ = open(r"D:/Program/dsh/g-series-e2e-20261004/lacZ_MG1655_CDS.fasta", encoding="utf-8").read()
lacZ_seq = "".join(l for l in lacZ.splitlines() if not l.startswith(">")).strip().upper()
r_lac = simulate_deletion_translation(lacZ_seq, 19, 133, 0, len(lacZ_seq), cds_strand="+")
check("lacZ 完整长 3075", len(lacZ_seq) == 3075, f"len={len(lacZ_seq)}")
check("删除 [19,133) frame preserved", r_lac["frame_preserved_by_length"] is True, r_lac["simulated_cds_length_bp"])
check("无内部终止", r_lac["premature_stop_detected"] is False, r_lac)
check("986 aa（去 terminal stop）", r_lac["protein_length_aa"] == 986, f"len={r_lac['protein_length_aa']}")
check("N 端前缀 MTMITDSD（与独立手算一致）",
      r_lac["translated_prefix"].startswith("MTMITDSD"), r_lac["translated_prefix"][:16])
check("terminal_stop 在末端", r_lac["terminal_stop"] is True, r_lac)
check("独立手算 987 密码子 = 986 aa + 1 terminal stop",
      r_lac["protein_length_aa"] == 986 and r_lac["terminal_stop"], r_lac)

print(f"\n{'=' * 60}")
print(f"GF-1/2/3 定向测试：{'ALL PASS' if not FAILURES else 'FAILED ' + str(len(FAILURES))}")
if FAILURES:
    print("失败项：", FAILURES)
    sys.exit(1)
sys.exit(0)
