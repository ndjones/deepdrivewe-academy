# Validation: CDK9 Smoke Test — Issues and GitHub Issue Proposals

**Date:** 2026-04-15
**Branch:** `feature/add-openmm-cdk9-cyclinT1-example`
**Scope:** Minimal end-to-end smoke test of both apo and holo CDK9 conditions
           using `config_smoke_apo.yaml` and `config_smoke_holo.yaml`
           (1 walker, 1 iteration, 1 ps segments, CPU, local executor).

---

## Overview

During smoke-test validation of the rebased CDK9/CyclinT1 example (new
2-agent `SimulationAgent` / `WestpaAgent` API), the following issues were
discovered.  Each is categorised by:

- **Scope:** CDK9 example only, or upstream `deepdrivewe-academy` framework
- **Severity:** Blocker / High / Medium / Low
- **Status:** Fixed locally, Workaround applied, or Open

---

## Issue 1 — Missing `deepdrivewe/workflows/stream.py`

**Severity:** Blocker (prevents any import of the package)
**Scope:** Upstream — `deepdrivewe-academy` (`ramanathanlab/deepdrivewe-academy`)
**Status:** Workaround applied locally (stub file created)

### Symptom
```
ModuleNotFoundError: No module named 'deepdrivewe.workflows.stream'
```

Triggered on `import deepdrivewe.simulation.openmm` — which happens
transitively whenever `deepdrivewe` is imported.

### Root cause
`deepdrivewe/simulation/openmm.py` has module-level imports:
```python
from deepdrivewe.workflows.stream import ProxyStreamConfig, SIMULATION_TOPIC
```
These symbols are only used by `CollectionReporter`, not by
`OpenMMSimulation` or `ContactMapRMSDReporter`.  However, because the
import is at module scope, the entire `openmm` module fails to load even
when `CollectionReporter` is never used.

The file `deepdrivewe/workflows/stream.py` does not exist in the
`ramanathanlab/deepdrivewe-academy` `develop` branch (formerly `develop`, merged April 2026).

### Local fix
Created `deepdrivewe/workflows/stream.py` stub:
```python
"""Stub for stream workflow configuration."""
from __future__ import annotations

SIMULATION_TOPIC: str = 'simulation'


class ProxyStreamConfig:
    """Stub ProxyStreamConfig — real implementation not yet ported."""

    def get_producer(self, topic: str) -> None:  # noqa: ARG002
        return None
```

### Proposed GitHub issue (upstream)
**Title:** `deepdrivewe/workflows/stream.py` missing from branch; blocks all
imports of `deepdrivewe.simulation.openmm`

**Body:**
The file `deepdrivewe/workflows/stream.py` is imported at module level by
`deepdrivewe/simulation/openmm.py` but does not exist in the
`develop` branch (formerly `develop`, merged April 2026).  This makes the entire package
unimportable.

**Reproduction:**
```python
import deepdrivewe.simulation.openmm
# ModuleNotFoundError: No module named 'deepdrivewe.workflows.stream'
```

**Proposed fix (option A — preferred):** Move the import inside
`CollectionReporter.__init__` or use a lazy import guard:
```python
def __init__(self, ...):
    from deepdrivewe.workflows.stream import ProxyStreamConfig, SIMULATION_TOPIC
    ...
```

**Proposed fix (option B):** Add `deepdrivewe/workflows/stream.py` with the
full `ProxyStreamConfig` implementation.

---

## Issue 2 — `BasisStates._glob_basis_states()` requires subdirectory layout

**Severity:** Blocker (workflow cannot start without valid basis states)
**Scope:** Upstream — `deepdrivewe-academy` (`ramanathanlab/deepdrivewe-academy`)
**Status:** Workaround applied locally (PDB files moved to subdirs)

### Symptom
```
ValueError: No basis states found in the basis state directory. Please
check that the basis_state_dir exists and contains the correct files with
the correct extension.
```

Triggered in `BasisStates.initialize_basis_states()`.

### Root cause
`BasisStates._glob_basis_states()` in `deepdrivewe/api.py` looks for
**subdirectories** inside `basis_state_dir`, then for a PDB inside each
subdirectory:

```python
sim_input_dirs = [
    p for p in self.basis_state_dir.glob('*') if p.is_dir()
]
for input_dir in sim_input_dirs:
    basis_state = next(input_dir.glob(pattern), None)
```

The CDK9 `inputs/` preparation scripts (`03_equilibrate.py` and
`00_minimal_basis.py`) save flat PDB files directly inside `basis_state_dir`:
```
inputs/apo/basis_000.pdb          ← flat file, NOT found
inputs/apo/00/basis_000.pdb       ← correct subdirectory layout
```

This behaviour is not documented anywhere in the API or README.

### Local fix
- Created `inputs/apo/00/basis_000.pdb` and `inputs/holo_cyclinT1/00/basis_000.pdb`
  (copied from flat files produced by `00_minimal_basis.py`).
- Updated `00_minimal_basis.py` to write directly to `<condition>/00/basis_000.pdb`.
- `03_equilibrate.py` also needs updating (see Issue 2b below).

### Proposed GitHub issue (upstream)
**Title:** `BasisStates._glob_basis_states()` subdirectory requirement is
undocumented; breaks all examples that don't use multi-walker equilibration

**Body:**
`BasisStates._glob_basis_states()` silently expects each basis state to live
in its own subdirectory (`basis_state_dir/<idx>/state.pdb`).  There is no
documentation of this contract in the docstring, the class definition, or the
YAML config comments.

When a user provides flat PDB files (`basis_state_dir/state.pdb`) the method
returns an empty list and raises a non-descriptive `ValueError` with no hint
that the layout is wrong.

**Proposed fix (option A — documentation):** Add a clear docstring paragraph
and a YAML comment explaining the required layout.

**Proposed fix (option B — error message):** In `_glob_basis_states()`,
detect flat PDB files and emit a helpful error:
```python
if not sim_input_dirs:
    flat_files = list(self.basis_state_dir.glob(f'*{self.basis_state_ext}'))
    if flat_files:
        raise ValueError(
            f'Found {len(flat_files)} PDB file(s) directly in '
            f'{self.basis_state_dir} but _glob_basis_states expects '
            f'each basis state in its own subdirectory. '
            f'Expected layout: basis_state_dir/00/state.pdb'
        )
```

**Proposed fix (option C — flexible API):** Accept both flat files and
subdirectory layout, falling back to flat when no subdirectories are found.

---

## Issue 2b — `03_equilibrate.py` saves flat PDB files (same root cause as Issue 2)

**Severity:** High (production equilibration script produces wrong layout)
**Scope:** CDK9 example (`examples/openmm_cdk9_cyclinT1/inputs/`)
**Status:** Open (needs update to `03_equilibrate.py`)

### Symptom
`03_equilibrate.py` saves `basis_<N>.pdb` flat in `inputs/apo/` and
`inputs/holo_cyclinT1/`.  When the user follows the `docs/quickstart.md`
instructions and then runs `main.py`, the workflow fails with the same
`ValueError` as Issue 2.

### Proposed fix
Update `03_equilibrate.py` so each equilibrated frame is saved as:
```
inputs/apo/<N:02d>/basis_<N:03d>.pdb
inputs/holo_cyclinT1/<N:02d>/basis_<N:03d>.pdb
```
This matches the subdirectory contract expected by `BasisStates._glob_basis_states()`.

---

## Issue 3 — Residue numbering mismatch: UniProt vs PDB 4BCI

**Severity:** High (wrong pcoord; silent incorrect results, not a crash)
**Scope:** CDK9 example and docs
**Status:** Fixed locally in all YAML configs and inline comments

### Symptom
No runtime error.  The salt-bridge distance pcoord (`pcoord[1]`) is computed
between wrong atoms, producing values that do not reflect the Glu66–Lys48
salt bridge.

### Root cause
The CDK9 canonical numbering (UniProt P50750) is Glu66 and Lys48.  The
4BCI crystal structure uses residue numbers offset by −4 (the crystallised
construct begins at CDK9 residue 5, so structure numbering = UniProt − 4):

| Residue | UniProt | PDB 4BCI |
|---------|---------|----------|
| Lys48   | 48      | **44**   |
| Glu66   | 66      | **62**   |

The original config defaults and YAML files used the UniProt numbers (66, 48),
so `CDK9PcoordReporter` targeted the wrong residues.

### Local fix
Updated all YAML config files:
- `config_apo.yaml`: `glu_resnum: 62`, `lys_resnum: 44`
- `config_holo_cyclinT1.yaml`: same
- `config_smoke_apo.yaml`: same (also `glu66_resnum: 62`, `lys48_resnum: 44`
  in `basis_state_initializer`)
- `config_smoke_holo.yaml`: same
Added inline YAML comments explaining the offset.

### Proposed GitHub issue (upstream / documentation)
**Title:** CDK9 example config comment: clarify UniProt vs PDB 4BCI residue
numbering offset (Glu66 = structure Glu62, Lys48 = structure Lys44)

**Body:**
The 4BCI crystal construct starts at CDK9 residue 5 (UniProt), so all
structure residue numbers are offset by −4 from UniProt canonical.  Users
following the quickstart and supplying their own `glu_resnum` / `lys_resnum`
values will compute the wrong pcoord if they use UniProt numbering without
this conversion.

**Proposed fix:** Add a comment in every config file at the relevant fields,
and a note in `inputs/04_verify_pcoord_residues.py`.

---

## Issue 5 — `LocalConfig` / `WorkstationConfig` use `address='localhost'`; fails on macOS

**Severity:** Blocker (Parsl interchange never starts; workflow cannot run)
**Scope:** Upstream — `deepdrivewe-academy` (`ramanathanlab/deepdrivewe-academy`)
**Status:** Fixed locally (`address='127.0.0.1'` in `deepdrivewe/parsl.py`)

### Symptom
```
ValueError: 'localhost' does not appear to be an IPv4 or IPv6 address
...
Exception: Interchange failed to start
```

Triggered in `parsl/addresses.py::tcp_url` when building the ZMQ bind URL.

### Root cause
`HighThroughputExecutor` passes `address` directly to `ipaddress.ip_address()`
when constructing the TCP URL for its ZMQ interchange process.
`ipaddress.ip_address('localhost')` raises `ValueError` because `localhost` is
a hostname, not a literal IP address.

On macOS, `/etc/hosts` maps `localhost` to `127.0.0.1` for DNS resolution, but
Parsl's `tcp_url` bypasses OS DNS and requires a literal IPv4 or IPv6 address.

Affects both `LocalConfig` and `WorkstationConfig` in `deepdrivewe/parsl.py`.

### Local fix
Changed `address='localhost'` → `address='127.0.0.1'` in both executor
constructors in `deepdrivewe/parsl.py`.

### Proposed GitHub issue (upstream)
**Title:** `LocalConfig` and `WorkstationConfig` fail on macOS with
`ValueError: 'localhost' does not appear to be an IPv4 or IPv6 address`

**Body:**
Both configs hard-code `address='localhost'` in `HighThroughputExecutor`.
Parsl's `tcp_url` calls `ipaddress.ip_address(address)` which rejects the
hostname `localhost` on macOS (and possibly Linux in strict networking envs).

**Reproduction:**
```bash
# macOS with Python 3.11
python main.py --config config_smoke_apo.yaml
# → Exception: Interchange failed to start
```

**Proposed fix:** Use `address='127.0.0.1'` (IPv4 loopback literal) for local
and workstation configs, or use `parsl.addresses.address_by_hostname()`:
```python
from parsl.addresses import address_by_hostname
HighThroughputExecutor(address=address_by_hostname(), ...)
```

---

## Issue 4 — `float('inf')` serialises to `null` in JSON / Pydantic

**Severity:** Low (YAML round-trip is fine; only affects JSON serialisation)
**Scope:** Upstream — `deepdrivewe-academy` (Pydantic BaseModel serialisation)
**Status:** Open (no local fix; does not block smoke tests)

### Symptom
When `ExperimentSettings` (or `InferenceConfig`) is serialised to JSON
(e.g., `cfg.model_dump_json()`), `float('inf')` values in
`rmsd_bin_edges` and `salt_bridge_bin_edges` appear as `null`:
```json
{"rmsd_bin_edges": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, null]}
```
YAML serialisation works correctly (`.inf` is a valid YAML float).

### Proposed GitHub issue (upstream)
**Title:** `InferenceConfig` bin edge lists lose `inf` sentinel when
serialised to JSON via Pydantic

**Body:**
Bin edge lists use `float('inf')` as the final element (required by
`MultiRectilinearBinner`).  Pydantic serialises `float('inf')` as `null`
in JSON mode.  This breaks any code that reads back a saved JSON config.

**Proposed fix:** Add a custom Pydantic serializer for `list[float]` fields
that converts `float('inf')` to the string `"inf"` (or `1e308`) in JSON:
```python
@field_serializer('rmsd_bin_edges', 'salt_bridge_bin_edges')
def serialize_edges(self, v: list[float]) -> list:
    return ['inf' if math.isinf(x) else x for x in v]
```

---

## Issue 6 — `LocalExchangeFactory` incompatible with `ParslPoolExecutor`

**Severity:** Blocker (workflow crashes on first task dispatch)
**Scope:** Upstream — `deepdrivewe-academy` example pattern; also affects
`examples/openmm_ntl9_hk/main.py`
**Status:** Fixed locally (CDK9 `main.py` now uses `executors=None` for local exchange)

### Symptom
```
_pickle.PicklingError: LocalExchangeFactory is not pickleable.
```

Raised inside `parsl/serialize/concretes.py` when Parsl tries to serialize
the agent (and its `Handle[WestpaAgent]`) to dispatch it to a subprocess worker.

### Root cause
`LocalExchangeFactory` is built on in-process shared memory (Python objects
in the same address space).  `ParslPoolExecutor` spawns a separate subprocess
via `HighThroughputExecutor` and must serialize everything via `dill`.
`LocalExchangeFactory` intentionally raises `PicklingError` (see
`academy/serialize.py`) because cross-process serialization would silently
break in-process queue semantics.

The NTL9 example (`examples/openmm_ntl9_hk/main.py`) uses the identical
pattern `LocalExchangeFactory + ParslPoolExecutor` and is affected by the
same issue.

### Architecture clarification
The two execution models are:

| Exchange | Executor | Works? |
|----------|----------|--------|
| `LocalExchangeFactory` | `executors=None` (event loop) | ✓ |
| `LocalExchangeFactory` | `ThreadPoolExecutor` | ✓ |
| `LocalExchangeFactory` | `ParslPoolExecutor` | ✗ (not pickleable) |
| `HttpExchangeFactory` (Globus) | `ParslPoolExecutor` | ✓ |

For local / smoke-test runs, the blocking MD simulation is still correctly
offloaded to a thread pool inside each `SimulationAgent.simulate()` via
`agent_run_sync()`, so `executors=None` does not block the event loop.

### Local fix (CDK9 `main.py`)
```python
if args.exchange == 'local':
    executor = None          # asyncio event loop; LocalExchangeFactory works
else:
    parsl_config = cfg.compute_config.get_parsl_config(...)
    executor = ParslPoolExecutor(parsl_config)  # requires Globus exchange

async with await Manager.from_exchange_factory(
    factory=create_exchange_factory(args.exchange),
    executors=executor,
) as manager:
    ...
```

### Proposed GitHub issue (upstream)
**Title:** Example `main.py` pattern `LocalExchangeFactory + ParslPoolExecutor`
fails with `PicklingError`; needs local-vs-distributed conditional

**Body:**
Both `examples/openmm_ntl9_hk/main.py` and the proposed CDK9 example
unconditionally pass `ParslPoolExecutor(parsl_config)` to
`Manager.from_exchange_factory`.  This fails immediately with:
```
_pickle.PicklingError: LocalExchangeFactory is not pickleable.
```
Because `LocalExchangeFactory` is in-process and Parsl requires cross-process
serialization.

**Proposed fix (option A):** Add a note in the example and docstring that
`ParslPoolExecutor` requires a cross-process exchange (Globus/HTTP).  Guard the
example:
```python
if args.exchange == 'local':
    executor = None
else:
    executor = ParslPoolExecutor(parsl_config)
```

**Proposed fix (option B):** Add a `LocalParslConfig` in `deepdrivewe/parsl.py`
that uses `ThreadPoolExecutor` rather than `HighThroughputExecutor`, making it
compatible with `LocalExchangeFactory`.

---

## Summary table

| # | Issue | Severity | Scope | Status |
|---|-------|----------|-------|--------|
| 1 | `deepdrivewe/workflows/stream.py` missing | Blocker | Upstream | Workaround (stub) |
| 2 | `BasisStates` requires undocumented subdir layout | Blocker | Upstream | Workaround (subdir created) |
| 2b | `03_equilibrate.py` saves flat files | High | CDK9 example | Open |
| 3 | Residue numbering: UniProt vs PDB 4BCI | High | CDK9 example | Fixed |
| 4 | `float('inf')` → `null` in JSON serialisation | Low | Upstream | Open |
| 5 | `LocalConfig` `address='localhost'` fails on macOS | Blocker | Upstream | Fixed locally |
| 6 | `LocalExchangeFactory + ParslPoolExecutor` PicklingError | Blocker | Upstream (NTL9 + CDK9) | Fixed locally |

---

## GitHub issues to file

File against `ramanathanlab/deepdrivewe-academy` on the
`develop` branch (formerly `develop`, merged April 2026):

1. **Issue 1** — Missing `stream.py` blocks all imports → propose lazy import fix
2. **Issue 2** — Undocumented subdir layout in `BasisStates` → propose better
   error message + documentation
4. **Issue 4** — `float('inf')` JSON serialisation → propose `field_serializer`
5. **Issue 5** — `address='localhost'` fails on macOS → use `127.0.0.1`
6. **Issue 6** — `LocalExchangeFactory + ParslPoolExecutor` incompatibility → guard examples with `exchange == 'local'` check

File as a documentation-only note / follow-up PR in
`ndjones/deepdrivewe-academy` (CDK9 example):

- **Issue 2b** — Update `03_equilibrate.py` to write subdir layout
- **Issue 3** — Already fixed; add note in PR description

---

## Validation run status

| Test | Config | Status | Notes |
|------|--------|--------|-------|
| Apo smoke | `config_smoke_apo.yaml` | ✅ PASSED | Exit 0; 1 iter, 1 walker, ~4 min CPU (macOS M-series) |
| Holo smoke | `config_smoke_holo.yaml` | ✅ PASSED | Exit 0; 1 iter, 1 walker, ~5 min CPU (macOS M-series) |

### Expected log output (both conditions)

A successful smoke test produces output matching this pattern:

```
INFO  (root) Configured logger (stdout-level=INFO, ...)
INFO  (MDAnalysis...) Setting segids from chainIDs ...
...
Loaded 1 basis states
INFO  (academy.exchange.local) Registered UserId<...> in exchange
INFO  (academy.manager) Initialized manager (UserId<...>)
INFO  (academy.manager) Launched agent (...; <class 'orchestrator.CDK9WestpaAgent'>)
INFO  (CDK9WestpaAgent) started (iteration=1, max=1)
INFO  (academy.runtime) Running agent (...; Agent<CDK9WestpaAgent>)
INFO  (academy.manager) Launched agent (...; <class 'simulate.CDK9SimulationAgent'>)
INFO  (CDK9SimulationAgent) started
INFO  (academy.runtime) Running agent (...; Agent<CDK9SimulationAgent>)
INFO  (CDK9SimulationAgent) running sim 0 iteration 1
...  [OpenMM runs for ~4–5 min on CPU] ...
INFO  (CDK9SimulationAgent) sim 0 complete
INFO  (CDK9WestpaAgent) received sim 0 iter 1. batch: 1/1
INFO  (CDK9WestpaAgent) running inference on 1 results for iteration 1
INFO  (CDK9WestpaAgent) [CDK9] walkers=1 aC_in_frac=1.00 (salt_bridge < 4 Å)
recycle_inds=array([], dtype=int64)
INFO  (CDK9WestpaAgent) iteration 1 complete. 1 walkers next.
INFO  (CDK9WestpaAgent) reached max iterations (1), shutting down.
INFO  (academy.manager) Closed manager (AgentId<...>)
...
INFO  (academy.manager) Closed manager (UserId<...>)
```

**Key lines to verify:**

| Line | Meaning |
|------|---------|
| `Loaded 1 basis states` | Basis state subdir layout resolved correctly |
| `CDK9SimulationAgent started` | Agent launched; Handle wiring OK |
| `running sim 0 iteration 1` | First (only) sim dispatched |
| `[CDK9] walkers=1 aC_in_frac=1.00` | pcoord computed; salt bridge < 4 Å in minimised structure (expected — structure starts near αC-in geometry) |
| `recycle_inds=array([], dtype=int64)` | RMSD < 6 Å threshold; no recycling (expected for minimised start) |
| `iteration 1 complete. 1 walkers next.` | Inference, resampling, and checkpointing completed |
| `reached max iterations (1), shutting down.` | Clean shutdown |
| Exit code 0 | End-to-end success |

**Observed pcoord values (both conditions):** `aC_in_frac = 1.00` — both the apo and holo energy-minimised structures start with the Glu62–Lys44 salt bridge in the αC-in conformation (~3.5 Å). This is consistent with PDB 4BCI (crystallised in the active/αC-in state). It does **not** imply that αC-in is the preferred ensemble state — distinguishing apo vs holo thermodynamics requires the full production run.

---

## Smoke test science analysis

This section documents what the smoke tests validate from a scientific
standpoint, and what trade-offs were made relative to the full production
workload.  It is intended as the authoritative reference; `docs/quickstart.md`
links to this section.

### Parameter comparison: smoke vs production

| Parameter | Smoke (both conditions) | Production (both conditions) | Scientific impact |
|-----------|------------------------|------------------------------|-------------------|
| `num_iterations` | 1 | 100 | No WE convergence; no landscape coverage |
| `initial_ensemble_members` | 1 | 40 | No ensemble; no weight redistribution |
| `simulation_length_ns` | 0.001 (1 ps) | 0.05 (50 ps) | Protein barely moves; pcoord is near-identical to start |
| `report_interval_ps` | 0.5 | 10.0 | 2 frames vs 5 frames; irrelevant at this length |
| `hardware_platform` | CPU | CUDA | ~10–100× slower per step; acceptable since segment is 1 ps |
| `rmsd_bin_edges` | 4 edges (coarse) | 7 edges (1 Å steps) | Coarse binning OK for 1 walker; fine grid needed for 40-walker resampling |
| `salt_bridge_bin_edges` | 3 edges (coarse) | 11 edges (2 Å steps) | Same |
| `sims_per_bin` | 1 | 4 | Resampler runs but makes no decisions with 1 walker |
| `max_allowed_weight` | 1.0 (uncapped) | 0.25 | Weight capping vacuous at 1 walker (weight = 1.0 trivially) |
| Basis state quality | Energy-minimised only | 2 ns NVT equilibrated | Starting structure may have strained geometry (see below) |
| `compute_config.name` | local | workstation | No Parsl; single-process asyncio |

### What the smoke tests do and do not validate

| Aspect | Validated? | Notes |
|--------|-----------|-------|
| OpenMM force field loads correctly | ✓ | AMBER ff14SB + GBn2 |
| PDB parses without errors | ✓ | Topology, positions, chain IDs |
| `CDK9PcoordReporter` computes RMSD + salt bridge | ✓ | Both numbers are finite and plausible |
| `SimResult` / `SimMetadata` round-trip intact | ✓ | Restart file written, pcoord stored |
| Academy agent startup / messaging / shutdown | ✓ | WestpaAgent ↔ SimulationAgent via Handle |
| `EnsembleCheckpointer` saves state | ✓ | Checkpoint written after iteration 1 |
| `MultiRectilinearBinner` assigns walker to bin | ✓ (trivially) | 1 walker → 1 bin |
| `HighRecycler` evaluates RMSD boundary | ✓ (no recycle needed) | RMSD of relaxed structure << 6 Å threshold |
| `HuberKimResampler` runs without error | ✓ (no-op) | 1 walker, no merge/split decisions |
| Conformational sampling of αC-helix | ✗ | 1 ps is ~4 orders of magnitude below relevant timescale |
| αC-in vs αC-out probability estimates | ✗ | Core scientific output; requires production run |
| WE weight convergence | ✗ | Requires O(100+) iterations with 40 walkers |
| Meaningful resampling events | ✗ | 1 walker fills 1 bin; resampler is vacuous |
| Detection of rare αC-out events (apo) | ✗ | Characteristic time ~10–100 ns; production target |
| CyclinT1 effect on αC-in fraction | ✗ | The scientific question; requires apo vs holo comparison at scale |

### Apo-specific analysis

The apo smoke test runs CDK9 alone (chain A, ~2,600 atoms). The single
basis state was produced by energy minimisation only (`00_minimal_basis.py`),
not by the 2 ns NVT equilibration run by `03_equilibrate.py`. This means
the starting velocities are randomised from a cold (near-0 K) coordinate set,
and any strained bonds or angles from PDBFixer are only partially resolved.

At 1 ps this is irrelevant — the system moves ~0.1–0.5 Å — but it means the
smoke test result is **not a sample from the equilibrium ensemble**. It is
a trajectory starting from a slightly non-physical geometry.

Expected production behaviour (100 iter × 40 walkers × 50 ps):
- Both αC-in (salt bridge ~3.5 Å) and αC-out (8–15 Å) should be sampled.
- WE walkers should bifurcate at the αC-in/αC-out barrier.
- The RMSD guard (recycler at 6 Å) should only activate for a small fraction
  of walkers.

### Holo-specific analysis

The holo smoke test runs CDK9 + CyclinT1 (chains A+B, ~4,700 atoms — 1.8×
larger than apo). The same parameter reductions apply. Additional holo-specific
considerations:

**System size:** 4,700 atoms vs 2,600 for apo. Production holo runs require
more GPU VRAM per worker (suggest 2–4 GPUs vs 4–8 for apo; see
`docs/quickstart.md` memory table).

**Interface geometry:** The smoke test starts from an energy-minimised complex.
The CDK9–CyclinT1 binding interface involves ~20–30 residues and will have
sub-optimal packing without equilibration. At 1 ps this is invisible in the
pcoord, but production basis states must come from `03_equilibrate.py` to
ensure the complex is pre-relaxed.

**CyclinT1 mutations (Q77R / E96G / F241L):** Present in PDB 4BCI, retained in
both smoke and production runs. All three are distal from the CDK9 interface
(13.4 / 6.7 / 28.9 Å; verified in `inputs/02_check_mutations.py`). No impact
expected on the αC-helix pcoord, but flagged for completeness.

Expected production behaviour (100 iter × 40 walkers × 50 ps):
- CyclinT1 is hypothesised to shift the ensemble toward αC-in (salt bridge
  ~3.5 Å) by direct contacts with the αC-helix.
- The expected scientific signal is a **shift in pcoord[1] distribution**
  relative to apo: holo walkers should spend more time in the 0–4 Å
  salt-bridge bins.
- The `[CDK9] walkers=N aC_in_frac=F` log line in `run_inference()` is the
  primary monitoring signal for this shift during the run.

**What apo vs holo smoke tests cannot tell us:**
The smoke tests confirm both system configurations parse, simulate, and report
correctly. They cannot confirm the CyclinT1 effect because:
1. 1 ps is thermally invisible — the salt bridge at frame 2 is almost
   identical to frame 1.
2. 1 walker is statistically meaningless.
3. The starting geometry of the minimised holo complex may not reflect the
   equilibrium pcoord distribution at all.

### Minimum scientifically meaningful run

To get any signal relevant to the biological question:

| Parameter | Minimum | Production target |
|-----------|---------|------------------|
| `num_iterations` | 10 | 100 |
| `initial_ensemble_members` | 10 | 40 |
| `simulation_length_ns` | 0.05 ns (50 ps) | 0.05 ns |
| Basis states | NVT-equilibrated (03_equilibrate.py) | NVT-equilibrated |
| `hardware_platform` | CPU (slow) or CUDA | CUDA |
| Estimated wall time (4× CUDA A100) | ~30 min | ~4–8 h per condition |

The 10-iteration / 10-walker minimum would give a rough landscape sketch but
would under-sample the αC-out state and give unreliable weight estimates. The
100-iteration / 40-walker production config is the Phase 1 scientific target.
