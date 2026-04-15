# Quickstart

## Compute expectations

The example has two distinct runtime profiles:

| Stage | Local CPU | GPU (CUDA) | Notes |
|-------|-----------|------------|-------|
| `01_download_and_clean.py` | ~1 min | — | Downloads PDB 4BCI |
| `02_check_mutations.py` | ~1 min | — | Optional; informational only |
| `03_equilibrate.py` | **3–5 h** | ~20–40 min | Both conditions; long-running |
| `04_verify_pcoord_residues.py` | ~1 min | — | Must pass before WE run |
| Smoke test (1 iter, 1 walker, 1 ps) | **~4–8 min** | — | Pipeline validation only; see below |
| WE run (100 iter, 40 walkers, 50 ps) | Not practical | Hours–days | Designed for multi-GPU |

**`03_equilibrate.py` is the critical long-running step.** Plan accordingly —
run it on a GPU workstation or overnight on CPU.  The WE workflow is designed
for multi-GPU execution; CPU-only smoke testing validates the pipeline but
produces no scientifically meaningful data (see
[`dev/validation.md` — Smoke test science analysis](../dev/validation.md#smoke-test-science-analysis)
for a full breakdown of trade-offs).

---

## Prerequisites

```bash
# From deepdrivewe-academy repo root
pip install -e .

# OpenMM + PDBFixer via conda-forge if not already installed:
# conda install -c conda-forge openmm pdbfixer
```

## Step 1 — Prepare structures

```bash
cd examples/openmm_cdk9_cyclinT1/inputs

python 01_download_and_clean.py     # ~1 min — downloads PDB 4BCI, extracts apo/holo PDBs
python 02_check_mutations.py        # optional — reports CyclinT1 mutation distances
python 03_equilibrate.py            # 3–5 h CPU or ~30 min GPU — plan accordingly
```

Before proceeding, verify the equilibrated structures are usable:

```bash
python 04_verify_pcoord_residues.py
```

This script checks that Glu66 and Lys48 are present with the expected atom
names in both prepared structures.  **Do not proceed to Step 2 if this fails**
— a residue numbering shift from PDBFixer will silently produce wrong pcoord
values throughout the WE run.

Expected output of a passing check:
```
apo:  Glu66 CD found at index N  |  Lys48 NZ found at index M
holo: Glu66 CD found at index N  |  Lys48 NZ found at index M
All checks passed.
```

## Step 2 — Run the weighted ensemble

```bash
# From examples/openmm_cdk9_cyclinT1/
export OPENMM_CPU_THREADS=1    # CPU only; remove this line for GPU

python main.py --config config_apo.yaml
python main.py --config config_holo_cyclinT1.yaml
```

## Step 3 — Resume from checkpoint

Re-run the same command — `EnsembleCheckpointer` loads the latest checkpoint
automatically.

---

## Configuration reference

Edit `config_apo.yaml` or `config_holo_cyclinT1.yaml`:

| Key | Default | Purpose |
|-----|---------|---------|
| `num_iterations` | 100 | WE iterations to run |
| `compute_config.available_accelerators` | 4 | Parallel simulation workers (= GPUs for GPU runs) |
| `simulation_config.openmm_config.hardware_platform` | `CUDA` | `CUDA`, `OpenCL`, or `CPU` |
| `simulation_config.openmm_config.simulation_length_ns` | 0.05 | Segment length (50 ps) |
| `inference_config.rmsd_boundary_ang` | 6.0 | RMSD recycling threshold (Å) — reduce to 4.0 if frequent recycling |
| `inference_config.sims_per_bin` | 4 | Target walkers per 2D bin cell |

### CPU smoke test

Dedicated smoke-test configs are provided; **do not edit the production
configs**.  The smoke configs use 1 walker, 1 iteration, and 1 ps
segments — enough to confirm the pipeline runs end-to-end without errors.

```bash
# Both conditions, ~4–8 min each on CPU
export OPENMM_CPU_THREADS=1
python main.py --config config_smoke_apo.yaml
python main.py --config config_smoke_holo.yaml
```

**Before running smoke tests** you must have the energy-minimised basis states:
```bash
cd examples/openmm_cdk9_cyclinT1/inputs
python 00_minimal_basis.py    # ~2 min; energy minimisation only (no NVT)
```

The smoke tests bypass `03_equilibrate.py` (which takes 3–5 h) and use the
minimised structure directly.  See
[`dev/validation.md` — Smoke test science analysis](../dev/validation.md#smoke-test-science-analysis)
for a detailed breakdown of what is and is not validated, and the scientific
trade-offs vs a production run.

---

## Expected outputs

```
runs/cdk9-apo/
├── params.yaml              Full resolved config
├── runtime.log              Application log
├── checkpoints/             Per-iteration ensemble state (HDF5)
└── simulations/
    └── iter_0001_sim_0000/
        ├── seg.pdb          Final frame — restart file for next iteration
        ├── seg.dcd          Trajectory
        ├── seg.log          Energy / temperature
        └── config.yaml      Simulation parameters
```

---

## Running on an HPC cluster (optional)

The example runs with `python main.py` on any machine with OpenMM installed.
The `scripts/` directory contains Slurm job scripts as a **starting-point
template** for HPC submission — they are not required and will not work
without cluster-specific edits.

Before submitting any script you must:

1. Add your environment activation (e.g. `conda activate myenv` or
   `source .venv/bin/activate`) in the `# Environment setup` section
2. Uncomment and set `#SBATCH --gres=gpu:N` and `--partition` to match
   your cluster's GPU resource syntax
3. Set `compute_config.available_accelerators` in the YAML config to
   match the GPU count

See `scripts/README.md` for the full checklist.

---

## Memory budgeting

| Condition | Approx. atoms | Suggested `compute_config.available_accelerators` |
|-----------|--------------|--------------------------------------------------|
| apo | ~2,600 | 4–8 (GPU) |
| holo_cyclinT1 | ~4,700 | 2–4 (GPU) — larger memory footprint |

Adjust based on available GPU VRAM.  Each worker holds one OpenMM simulation
in memory simultaneously.
