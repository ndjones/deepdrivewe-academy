# Technical Specification

## Framework status

> **Read before making architectural changes.**

This example is built on `ndjones/deepdrivewe-academy`
(`feature/add-openmm-cdk9-cyclinT1-example`), forked from
`ramanathanlab/deepdrivewe-academy:develop`.

The example has been rebased (April 2026) from the earlier
proof-of-concept 4-agent topology onto the new 2-agent API:
`SimulationAgent` + `WestpaAgent` via `run_westpa_workflow()`.

Implications:
- The example targets `ramanathanlab/deepdrivewe-academy` and should be
  tracked against upstream changes there.
- Confirm with the deepdrivewe developers before making significant
  architectural additions — the upstream branch is still in active
  development.
- The subclassing approach (`CDK9PcoordReporter`, `CDK9SimulationAgent`,
  `CDK9WestpaAgent`) is intentionally minimal and should be stable
  across minor upstream API updates.

---

## Architecture baseline

Built on deepdrivewe + Academy agents, following the NTL9 Academy example
(`examples/openmm_ntl9_hk_academy/`) as the reference pattern.  All
CDK9-specific code subclasses deepdrivewe base classes without modifying the
core library.

| Agent | Role | CDK9 subclass |
|-------|------|---------------|
| `SimulationAgent` | Runs OpenMM MD (sync), computes pcoord | `CDK9SimulationAgent` |
| `WestpaAgent` | WE state, binning, resampling, recycling | `CDK9WestpaAgent` |

`run_westpa_workflow()` wires both agents and drives the iteration loop.
No manual agent launching needed.

Config models (defined in example files):

| Model | File | Contents |
|-------|------|----------|
| `SimulationConfig` | `simulate.py` | `openmm_config` + CDK9 reporter fields |
| `InferenceConfig` | `orchestrator.py` | binner edges, resampler weights, recycler threshold |
| `ExperimentSettings` | `main.py` | top-level YAML root |

## Progress coordinate design

Two scalar values computed per frame; stored as `SimMetadata.pcoord`
shape `(n_frames, 2)`.

**pcoord[0] — CDK9 Cα RMSD (Å)**
Global structural drift over all CDK9 Cα atoms relative to the equilibrated
reference structure.  Acts as a containment guard — not a sampling coordinate.
Without it, a 1D binner over the salt-bridge distance alone would retain walkers
in biologically meaningless unfolded states.

**pcoord[1] — Glu66 Cδ – Lys48 Nζ distance (Å)**
The canonical kinase αC-helix activation state metric.  A conserved salt bridge
between the αC-helix glutamate (Glu66) and the β3-strand lysine (Lys48) forms
at ~3.5 Å when the αC-helix is in the active "αC-in" conformation.  CyclinT1
binding is known to stabilise αC-in; apo CDK9 is expected to sample αC-out
(8–15 Å) more frequently.

This axis directly reports on the biological question.  It is also
mechanistically linked to inhibitor selectivity — Type I inhibitors bind
the αC-in state; Type I½ inhibitors exploit the αC-out state and show
selectivity differences depending on whether CyclinT1 is present.

### Alternatives considered and deferred

| Option | Metric | Reason deferred |
|--------|--------|----------------|
| B | Phe168 Cζ – gatekeeper (Phe103) distance | DFG-in/out; less directly coupled to CyclinT1 interface |
| C | αC-helix RMSD (residues ~58–75) | Coarser than salt-bridge distance; harder to interpret |
| D | CDK9–CyclinT1 interface RMSD | Undefined for the apo condition |

Options B/C/D remain available for Phase 2 if pcoord[1] proves insufficient to
differentiate the apo and holo landscapes.

## Binning

2D uniform grid via `MultiRectilinearBinner` (built-in:
`deepdrivewe.binners.multirectilinear`).  Default: 7 RMSD bins × 11
salt-bridge bins = 77 cells.  Uses row-major flat indices via
`scipy.stats.binned_statistic_dd`.  Bin edges are configurable in
`inference_config` in the YAML and should be verified against the actual
pcoord distribution after the first test run.

## Recycling

`HighRecycler` (built-in: `deepdrivewe.recyclers.high`) replaces the
earlier custom `BoundaryRecycler`.

`LowRecycler` drives walkers toward a target state (appropriate for
folding simulations).  CDK9 Phase 1 has no target state — the goal is
to *map* the landscape.  `HighRecycler` recycles walkers where
`pcoord[pcoord_idx] > target_threshold` (here: `pcoord[0] > 6 Å`),
preventing unfolded states from consuming compute without biasing the
ensemble toward any specific conformation.

## Solvent

GBn2 implicit solvent (`amber14-all.xml` + `implicit/gbn2.xml`) for Phase 1.
Reduces compute cost and eliminates the need for periodic box, pressure
coupling, and water equilibration.  Adequate for mapping which states exist
and their rough probabilities.  Phase 2/3 should move to explicit solvent
for quantitative rate estimates.

## Subclassing approach

All CDK9 code subclasses deepdrivewe base classes; nothing is added to the core
library.  This keeps the example self-contained and avoids breaking changes for
other examples.

In the new 2-agent API, `run_simulation()` and `run_inference()` are **sync**
methods — do not add `@action` or `async` to them.  The framework handles async
dispatch internally via `SimulationAgent.simulate()` and
`WestpaAgent.run_westpa()` in `deepdrivewe/workflows/westpa.py`.

## Contact maps in Phase 1

`CDK9PcoordReporter` inherits contact-map collection from the parent class
`ContactMapRMSDReporter`.  Maps are stored in `SimResult.data['contact_maps']`
and unused in Phase 1 but essential for Phase 2 CVAE warm-start, avoiding
the need to re-run trajectories.  Note that apo and holo produce different
contact map sizes (321 vs. 573 residues) — do not train a single CVAE on
both without alignment or padding.

## Agentic HPC deployment

Academy has explicit support for HPC job dispatch via the **Globus connector**.
This is the supported agentic pathway for sites that have Globus compute
endpoints — an Academy agent can submit, monitor, and retrieve jobs without
manual SSH intervention.  This example does not currently wire up the Globus
connector; the WE workflow is launched with `python main.py` and the `scripts/`
directory provides manual Slurm templates for direct submission.

A future extension could replace the manual submission path with an
Academy-native `GlobusComputeAgent` wrapping the equilibration and WE runs,
making the full pipeline end-to-end agentic for sites with Globus support.

## Inputs pipeline outside Academy

The four `inputs/` scripts (`01_download_and_clean.py` through
`04_verify_pcoord_residues.py`) run as plain Python outside any Academy agent.
This is the current gap between the fully agentic vision and the Phase 1
implementation.

A natural future generalization is to wrap these as Academy agents:
- A `StructurePrepAgent` handling download, cleaning, and mutation checks
- An `EquilibrationAgent` wrapping `03_equilibrate.py` and emitting validated
  basis states
- A `ValidationAgent` running `04_verify_pcoord_residues.py` and gating
  downstream work

This would make the full pipeline — structure preparation, equilibration, and
WE sampling — orchestratable end-to-end through Academy, including via the
Globus connector for HPC sites.  Capturing this now so it is not lost as a
design direction.

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-14 | Target: CDK9/CyclinT1, PDB 4BCI | Defined by biological question; T3E removed, phospho-Thr186 retained |
| 2026-04-14 | Binding partner: CyclinT1 (chain B) | Obligate activating subunit; directly implicated in inhibitor selectivity |
| 2026-04-14 | pcoord[1]: Glu66–Lys48 salt bridge | Canonical CDK activation metric; directly reports CyclinT1 effect; linked to inhibitor binding mode selectivity |
| 2026-04-14 | Phase 1 geometric pcoord first | No existing MD data; avoids CVAE cold-start; validates pipeline on real system |
| 2026-04-14 | Independent apo/holo runs in Phase 1 | Simpler than coupled orchestration; sufficient for initial landscape comparison |
| 2026-04-14 | Implicit solvent (GBn2) for Phase 1 | Reduced compute; acceptable for landscape topology; flag for explicit in Phase 2+ |
| 2026-04-14 | HighRecycler over LowRecycler | No target state; upper RMSD bound only to prevent unfolding |
| 2026-04-15 | Rebase to 2-agent API | ramanathanlab/deepdrivewe-academy branch adopts SimulationAgent+WestpaAgent; old 4-agent topology retired |
| 2026-04-15 | MultiRectilinearBinner replaces Rectilinear2DBinner | Built-in N-D binner now exists; custom class deleted |
| 2026-04-15 | HighRecycler replaces BoundaryRecycler | Built-in high-threshold recycler now exists; custom class deleted |
| 2026-04-14 | Subclass, don't modify core | Self-contained example; no breaking changes to deepdrivewe |
| 2026-04-14 | Collect contact maps in Phase 1 | Phase 2 CVAE needs them; avoids re-running trajectories |
| 2026-04-14 | Example placed in deepdrivewe repo | Self-contained community reference; demonstrates agentic development workflow |
