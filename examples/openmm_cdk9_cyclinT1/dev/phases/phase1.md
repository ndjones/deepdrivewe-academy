# Phase 1 — Geometric Pcoord, Independent Conditions

**Branch:** `feature/add-openmm-cdk9-cyclinT1-example` (`ndjones/deepdrivewe-academy`)
**Status:** Code complete — rebased to new 2-agent API (April 2026)

## Intent

Establish the minimum viable landscape-sampling workflow for CDK9/CyclinT1.
Replace the NTL9-derived single-scalar RMSD pcoord with a 2D geometric pcoord
grounded in CDK9 biology.  Remove target-directed recycling.  Run apo and holo
as two independent experiments compared post-hoc.  This phase validates the
pipeline on the real system before introducing ML-based pcoords.

No compute-environment optimisations are made.  The workflow is portable across
desktop CPU, HPC cluster, and cloud GPU.  The key tuning knobs per environment
are `compute_config` (Parsl executor type and accelerator count) and
`simulation_config.openmm_config.simulation_length_ns`.

## System preparation

### Condition A — apo CDK9
- Extract chain A from 4BCI; remove T3E + CyclinT1
- Retain phospho-Thr186 (TPO) with AMBER ff14SB + PHOSAA10
- GBn2 implicit solvent; energy minimise + 2 ns NVT equilibration
- Save 10 snapshots in numbered subdirectories:
  `inputs/apo/00/basis_000.pdb` … `inputs/apo/09/basis_009.pdb`
  (Subdirectory layout required by `BasisStates._glob_basis_states()`;
  see `dev/validation.md` Issue 2)

### Condition B — holo CDK9 + CyclinT1
- Extract chains A + B from 4BCI; remove T3E only
- Same phospho-Thr186 treatment
- GBn2 implicit solvent; energy minimise + 2 ns NVT equilibration
- Save 10 snapshots in numbered subdirectories:
  `inputs/holo_cyclinT1/00/basis_000.pdb` … `inputs/holo_cyclinT1/09/basis_009.pdb`

Run `inputs/03_equilibrate.py` directly.  **Always verify residue numbering
with `inputs/04_verify_pcoord_residues.py` after preparing a fresh structure**
— PDBFixer can shift residue indices.

## Progress coordinate implementation

`CDK9PcoordReporter` subclasses `ContactMapRMSDReporter`:
- `report()`: computes per-frame Cα RMSD (MDAnalysis `rms.RMSD`) and
  Glu66 Cδ – Lys48 Nζ distance (MDAnalysis `distances.dist`); atom indices
  resolved lazily on first call
- `get_rmsds()`: returns `np.column_stack([rmsd, sb])` — shape `(n_frames, 2)`

`CDK9SimulationAgent` subclasses `SimulationAgent` (new 2-agent API);
implements sync `run_simulation(metadata: SimMetadata) -> SimResult` to
inject `CDK9PcoordReporter` in place of the default reporter.  The
framework offloads this to a thread pool via the parent's `@action simulate()`.

Residue numbering follows PDB 4BCI / UniProt P50750.

## Binning

`MultiRectilinearBinner` (built-in: `deepdrivewe.binners.multirectilinear`)
with default bin edges in `inference_config`:
- `pcoord[0]` (RMSD, Å): `[0, 1, 2, 3, 4, 5, 6, inf]` — 7 bins
- `pcoord[1]` (salt-bridge, Å): `[0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, inf]` — 11 bins

After the first 2–3 test iterations, inspect the actual pcoord distribution
and rescale edges accordingly.  The αC-helix salt-bridge will cluster near
3–4 Å in the holo condition and spread up to ~15 Å in the apo.

## Recycling

`HighRecycler` (built-in: `deepdrivewe.recyclers.high`) configured via
`inference_config.rmsd_boundary_ang: 6.0`.  Recycles walkers where
`pcoord[0] > rmsd_boundary_ang` back to a randomly selected basis state.
Reduce to 4 Å if frequent recycling is observed in early iterations.

## αC-in monitoring

`CDK9WestpaAgent.run_inference()` logs per-iteration:
- Fraction of active walkers with `pcoord[1] < 4 Å` (αC-in fraction)
- Logged via `self.logger.info` each time inference runs

## Comparative analysis (post-hoc)

Run both conditions independently then compare offline:
- 2D bin occupation heatmaps: apo vs. holo and difference map
- Marginal weight distribution over pcoord[1] — the key quantitative result
- Contact map differences: per-residue-pair contact probability apo vs. holo
- CVAE latent space overlay (Phase 2 warm-start seed)

Notebook: `analysis/compare_landscapes.ipynb` — planned, not in this phase.

## Deliverables

- [x] `inputs/00_minimal_basis.py` — energy-minimise only (smoke test; skips 2 ns NVT)
- [x] `inputs/01_download_and_clean.py` — download 4BCI, prepare apo/holo PDBs
- [x] `inputs/02_check_mutations.py` — CyclinT1 mutation proximity analysis
- [x] `inputs/03_equilibrate.py` — minimise + 2 ns NVT + save basis states (**needs subdir update**)
- [x] `inputs/04_verify_pcoord_residues.py` — verify Glu66/Lys48 numbering
- [x] `inputs/apo/00/basis_000.pdb` + `inputs/holo_cyclinT1/00/basis_000.pdb` — smoke test basis states
- [x] `simulate.py` — `SimulationConfig` + `CDK9PcoordReporter` + `CDK9SimulationAgent`
- [x] `orchestrator.py` — `InferenceConfig` + `CDK9WestpaAgent`
- [x] `main.py` — entry point, `ExperimentSettings`, `run_westpa_workflow()`
- [x] ~~`recyclers.py`~~ — deleted; replaced by built-in `HighRecycler`
- [x] ~~`binners.py`~~ — deleted; replaced by built-in `MultiRectilinearBinner`
- [x] `config_apo.yaml` + `config_holo_cyclinT1.yaml` — production configs
- [x] `config_smoke_apo.yaml` + `config_smoke_holo.yaml` — smoke test configs (1 walker, 1 iter, CPU)
- [x] `dev/validation.md` — smoke test results, 6 upstream issues, science analysis
- [ ] `inputs/03_equilibrate.py` — update to write subdirectory layout (`00/`, `01/`, …) required by
  `BasisStates._glob_basis_states()` (see validation.md Issue 2b; currently saves flat files)
- [ ] `scripts/` — Slurm template scripts for HPC deployment; **not required
  to run the example**.  Require cluster-specific editing before use:
  environment activation, GPU/partition directives, and accelerator count
  alignment.  See `scripts/README.md`.
- [x] `docs/quickstart.md` — usage guide
- [x] `dev/` — intent, spec, phase plans, and validation
- [ ] Basis state PDBs (production) — not committed (generated by `inputs/03_equilibrate.py`)
- [ ] `analysis/compare_landscapes.ipynb` — post-run analysis notebook

## Smoke test status

Both minimal smoke tests passed April 2026 on macOS (Apple M-series, Python 3.11,
single CPU core).  See `dev/validation.md` for full results and science analysis.

| Test | Wall time | Exit |
|------|-----------|------|
| `config_smoke_apo.yaml` | ~4 min | 0 ✅ |
| `config_smoke_holo.yaml` | ~5 min | 0 ✅ |

## Known issues

**CDK9 example:**
- **Residue numbering:** PDB 4BCI residue numbers are offset −4 from UniProt P50750
  canonical (structure starts at CDK9 residue 5). Config files use structure
  numbering (Glu62/Lys44). Always verify with `04_verify_pcoord_residues.py`.
- **`03_equilibrate.py` flat file layout:** Currently saves `basis_N.pdb` flat in
  `inputs/apo/` and `inputs/holo_cyclinT1/` — wrong for `BasisStates._glob_basis_states()`.
  Needs update to write `inputs/apo/NN/basis_NNN.pdb` subdirectory layout.
  See `dev/validation.md` Issue 2b.
- **holo system size:** ~4,700 atoms vs. ~2,600 for apo.  Budget VRAM
  accordingly when setting `compute_config.available_accelerators`.
- **GBn2 loop drift:** Reduce `rmsd_boundary_ang` to 4 Å if frequent recycling
  is observed in early iterations.
- **Contact map shape mismatch:** Apo and holo produce different contact map
  sizes.  Do not train a single CVAE on both without alignment or padding.

**Upstream framework issues (filed against ramanathanlab/deepdrivewe-academy):**

See `dev/validation.md` for full analysis.  Summary of issues with local workarounds
committed to `ndjones/deepdrivewe-academy`:

| # | Issue | Workaround in this branch |
|---|-------|--------------------------|
| upstream-1 | `deepdrivewe/workflows/stream.py` missing | Stub file created |
| upstream-2 | `BasisStates` subdir layout undocumented | Subdir structure created; noted in docs |
| upstream-4 | `float('inf')` → `null` in JSON | No fix; YAML round-trip unaffected |
| upstream-5 | `address='localhost'` fails on macOS | `deepdrivewe/parsl.py` uses `127.0.0.1` |
| upstream-6 | `LocalExchangeFactory + ParslPoolExecutor` incompatible | `main.py` uses `executors=None` for `--exchange local` |
