# dsh-bio-graft

> Gene-editing design specialty plugin for [dsh](https://github.com/deepseek-ai/deepseek-harness)
> *(graft = grafting designed sequence changes into an existing genome)*

**graft** is the gene-editing member of the **dsh-bio** plugin family:

| Plugin | Role |
|---|---|
| **dsh-bio-genie** | General bioinformatics host: 50+ semantic tools, self-bootstrapping Python, publication-grade figures |
| **dsh-bio-gem** | Genome-scale metabolic models: build / validate / gap-fill / ledger |
| **dsh-bio-graft** | Gene-editing design: sgRNA candidates, score vectors, off-target scanning, EditPlan ledger |

## Integration status (2026-09-14)

| Capability | Status |
|---|---|
| `graft_*` tools registered alongside the host's `bio_*` tools | ✅ implemented |
| `graft-expert` skill (reaches the agent's skill catalog) | ✅ implemented |
| Hosted-domain integration API (`/api/dsh-bio-graft/integration/health`, `/v1/status`) | ⚠️ payload still in its early shape — not yet aligned with the host's protocol v2 (batch B) |
| BioGenie settings panel "gene-editing" conditional tab | ❌ not implemented yet (batch B) |
| Host `persona` capability-domain routing (existence-aware) | ❌ not implemented yet (batch B) |

Until batch B lands, graft is reachable **only through the tool registry** — its install state is
not shown in the BioGenie panel.

## Design principles

**Desired edit first, tool second** — the user describes the edit they want; modality
(nuclease / base editing / prime editing / HDR / paired deletion) is compared before any tool choice.

**Score vectors, never a composite score** — every candidate keeps its full score vector
(GC, homopolymers, self-palindrome, U6 start preference, seed sequence). `87.3 / 100` is false
precision; ranking is done by a **declared objective** and recorded in the ledger.

**Every geometry carries its own convention** — candidates expose `start_0`/`end_0`
(0-based half-open, PAM included) plus **`cut_site_0`** with `cut_site_convention` (a human-readable
string) and `cut_site_verified` (whether that nuclease's geometry has been checked against primary
literature). Numbers without a convention do not go into a report.

**Evidence grading** — every `NucleaseProfile` carries `verified` + `pam_source`;
`verified=false` (currently Cas12b / Cas13a) means the PAM/geometry is **not yet checked against
primary literature** and must be reported as such.

**The EditPlan is an auditable scientific object** — iterations append to
`<name>.editplan.json` + an append-only `runs/` ledger (monotonic run numbers, atomic writes,
no same-name overwrite). It answers *"why was guide B recommended yesterday and guide D today?"*

**Off-target iron rule** — *no computational off-target method may label a design as safe.*
Every result carries a machine-readable `interpretation_boundary`; zero hits additionally return a
`zero_hit_warning` listing the usual false-negative causes. The only allowed phrasing is
"no high-scoring site detected under these search parameters".

## Tools (9)

| Tool | Purpose |
|---|---|
| `graft_profiles` | NucleaseProfile registry (PAM / spacer / geometry + `verified` / `pam_source`) |
| `graft_design` | Bidirectional PAM scan → sgRNA candidates + score vector + **cut site** (IUPAC-aware; FASTA / raw / multi-record) |
| `graft_score` | (Re)score an existing candidate list (no composite score) |
| `graft_rank` | **Declarative ranking** (pareto / lexicographic / weighted-with-explicit-weights): returns `policy_id` + `policy_digest`, per-candidate exclusion reasons, and treats missing data as `not_searched` (never a silent pass) |
| `graft_offtarget` | Cas-OFFinder scan → **structured hits** + `search_completeness` (what was *not* searched) + `assessment` (refuses safety conclusions) + `per_guide` aggregation; supports `preflight_only` genome checks and `device=auto` |
| `graft_base_edit` | **Base-editing design** (CBE/ABE): editable bases in the window + **bystanders** + codon consequences (synonymous/missense/nonsense/stop_loss); strand semantics triad (a minus-guide C→T is a **G→A** on the reference plus strand); five-layer profile with `window_evidence` |
| `graft_backend_status` | Backend probe (`status`) / OpenCL device list (`devices`) / auto-install (`ensure`, Windows only) |
| `graft_plan_save` | EditPlan write (`new` / `add_run` / `update_recommendation`) |
| `graft_plan_load` | EditPlan read-back (plan + full runs timeline) |

## Install

```bash
dsh plugin add @dsh-bio/dsh-bio-graft --profile web
```

## Runtime requirements

| Requirement | Notes |
|---|---|
| Python ≥3.10 | Reuses the host's bootstrapped environment (`GRAFT_PYTHON` overrides); all graft ops are stdlib-only |
| Cas-OFFinder (optional) | Official Windows x86-64 binary v2.4.1 (BSD-3); `graft_backend_status action=ensure` downloads it to `~/.dsh/dsh-bio-graft/bin/` |
| OpenCL runtime | Cas-OFFinder needs an OpenCL device (GPU drivers usually ship one; CPU-only use needs an Intel/AMD OpenCL runtime). Query with `action=devices`; `device=auto` picks one |

> Measured on this machine (NVIDIA RTX 3050 + AMD gfx90c): there is **no CPU OpenCL device**,
> so `device=C` fails immediately with `No OpenCL devices found.` — hence `device=auto`
> (which reports the device it actually used and why).

## Data directory

```
~/.dsh/dsh-bio-graft/
├── bin/cas-offinder.exe        # auto-installed off-target backend
├── tmp/                        # Cas-OFFinder inputs and raw hit files
└── plans/
    ├── <name>.editplan.json     # current recommendation + state (monotonic last_run_number)
    └── <name>/runs/             # append-only ledger (001_new.json, 002_add_run.json, …)
```

## Self-check

```bash
npm test                 # tool contract + golden ops + real off-target scan (62 assertions)
GRAFT_STRICT=1 npm test  # strict: probes/skips become FAIL (CI mode)
```

## Safety boundary (architecture-level gate, documented in the skill)

- **Level 0** routine research (non-pathogenic microbes / cell lines / model organisms): normal design support
- **Level 1** human somatic research: design + off-target review allowed, but must state
  `research design ≠ clinical suitability`
- **Level 2** clinical decision-making: downgrade to evidence/risk-analysis mode
- **Level 3** heritable human editing / pathogen enhancement: no executable sequence design

## License & third parties

MIT. **No license-incompatible third-party code is bundled**: Cas-OFFinder (BSD-3) is used as an
external binary fetched by the user's machine; FlashFry (GPL-3+) / PrimeDesign (AGPL + commercial) /
inDelphi (non-commercial) / CRISPResso2 (non-commercial academic EULA) are **external adapters only**.
See `THIRD_PARTY_NOTICES.md`.

## Roadmap (batches, not version numbers)

| Batch | Content | Status |
|---|---|---|
| A | Trust foundation: FASTA / IUPAC / real Cas-OFFinder contract / cut sites / ledger hardening + test net | ✅ done |
| B | Contract integration: integration v2 payload + `capabilities.json` + host domain registry / conditional tab / persona routing | planned |
| C | Off-target semantics (per-guide aggregation, seed distribution) + declarative `graft_rank` + EditPlan 0.2 | planned |
| D | Base editing (`BaseEditorProfile` + `graft_base_edit` + bystanders / codon consequences) | planned |

---

*Part of the **dsh-bio** plugin family · `@dsh-bio/dsh-bio-graft`*
