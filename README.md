# Conditional Autonomy

Research and implementation artifacts for a self-improving agent architecture
designed for smaller language models. The system combines deterministic policy
boundaries, supervisor and worker agents, evidence-preserving environment
state, post-training feedback loops, and specialist LoRA adapters.

## Current status

Workstream 1A defines the machine-readable contracts for the architecture.
Batch 0 is validated and committed. Batch 1 and Batch 2 are technically green
and have completed independent specification-fidelity review. Batch 3 remains
dependency-blocked pending integration of its required contracts.

## Authoritative materials

- `architecture/schemas/v1.0/` — current schema package, validation harness,
  fixtures, deferred invariants, and ticket registry.
- `outputs/Thesis_Architecture_Formalization_v1.1.2.docx` — latest formal
  architecture specification.
- `outputs/Workstream_1A_Orchestrator_Handoff.md` — current implementation
  handoff.
- `outputs/Workstream_1A_Plan_Amendments.md` — approved schema-plan amendments.

## Historical and generated materials

- `architecture/schemas/v0.1/` is preserved as a non-authoritative historical
  prototype.
- Earlier formalization documents are retained as research history.
- `work/` contains reproducibility scripts. Rendered PDF inspection files are
  generated locally and ignored by Git.
- Generated ZIP packages are ignored by Git.

## Validate the schema package

Install the pinned validators:

```powershell
python -m pip install --target architecture\schemas\.vendor -r architecture\schemas\requirements-schema.txt
```

Run the gate:

```powershell
python architecture\schemas\v1.0\scripts\check_schemas.py --batch batch0
python architecture\schemas\v1.0\scripts\check_schemas.py --batch batch1
python architecture\schemas\v1.0\scripts\check_schemas.py --batch batch2
python architecture\schemas\v1.0\scripts\check_schemas.py --batch all
```

The gate must remain green after every schema integration.
