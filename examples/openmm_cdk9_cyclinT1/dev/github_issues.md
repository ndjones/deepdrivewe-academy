# GitHub Issues — Upstream ramanathanlab/deepdrivewe-academy

Issues discovered during smoke-test validation of the CDK9/CyclinT1 example
(April 2026, `ndjones/deepdrivewe-academy` branch
`feature/add-openmm-cdk9-cyclinT1-example`).

File against: **https://github.com/ramanathanlab/deepdrivewe-academy/issues/new**
Target branch for fixes: `develop`

Each issue body below can be copy-pasted directly.  PRs with fixes are
noted where they exist.

**Upstream audit performed April 2026 against
`ramanathanlab/deepdrivewe-academy:develop` (post-transfer from
`braceal/deepdrivewe-academy`, commit `07730f8 transfer ownership`).**
Issues B and E remain unresolved on `develop`.
Issues A and C were resolved upstream before filing — bodies retained for reference only.
Issue D: core incompatibility persists; fix branch prepared at
`ndjones:bugfix/no-issue-local-exchange-parsl-guard`.

---

## Issue A — ~~`deepdrivewe/workflows/stream.py` missing~~  RESOLVED UPSTREAM

> **Status: RESOLVED** — commit `a71d92b remove streaming logic` on
> `ramanathanlab/deepdrivewe-academy:develop` removed the module-level
> imports and stripped `stream_config` from `CollectionReporter`.
> The package now imports cleanly without `stream.py` existing.
> The stub committed to this branch (`deepdrivewe/workflows/stream.py`)
> should be removed before the CDK9 example PR is merged.
> Body retained for historical reference only.

**Title:**
> `deepdrivewe/workflows/stream.py` missing; blocks all imports of
> `deepdrivewe.simulation.openmm`

**Labels:** `bug`, `priority: high`

**Body:**
```
## Summary

`deepdrivewe/simulation/openmm.py` has a module-level import:

    from deepdrivewe.workflows.stream import ProxyStreamConfig, SIMULATION_TOPIC

but `deepdrivewe/workflows/stream.py` does not exist in the repository.
This makes the entire `deepdrivewe` package unimportable.

## Reproduction

    import deepdrivewe
    # ModuleNotFoundError: No module named 'deepdrivewe.workflows.stream'

## Root cause

`ProxyStreamConfig` and `SIMULATION_TOPIC` are only used inside
`CollectionReporter`, not by `OpenMMSimulation` or
`ContactMapRMSDReporter`. Because the import is at module scope, any code
that does `from deepdrivewe.simulation.openmm import OpenMMSimulation`
fails even though `CollectionReporter` is never used.

## Proposed fix (preferred) — move import inside CollectionReporter

    class CollectionReporter:
        def __init__(self, ...):
            from deepdrivewe.workflows.stream import (
                ProxyStreamConfig, SIMULATION_TOPIC)
            ...

## Proposed fix (alternative) — add the missing module

Create `deepdrivewe/workflows/stream.py` with a full implementation
of `ProxyStreamConfig` and the `SIMULATION_TOPIC` constant.

## Context

Discovered while validating the CDK9/CyclinT1 example (PR forthcoming).
A local stub workaround was applied in `ndjones/deepdrivewe-academy`:

    SIMULATION_TOPIC: str = 'simulation'
    class ProxyStreamConfig:
        def get_producer(self, topic: str) -> None:
            return None

PR with fix: [link after opening]
Environment: Python 3.11, macOS (Apple M-series), deepdrivewe develop
```

---

## Issue B — `BasisStates._glob_basis_states()` subdir layout undocumented; error message unhelpful

**Title:**
> `BasisStates._glob_basis_states()` requires undocumented subdirectory
> layout; error message does not explain expected structure

**Labels:** `bug`, `documentation`

**Body:**
```
## Summary

`BasisStates._glob_basis_states()` silently expects each basis state to
live in its own numbered subdirectory (`basis_state_dir/00/state.pdb`),
but this contract is not documented in the class, the docstring, or any
example config comment.

When a user provides flat PDB files directly in `basis_state_dir/` the
method returns an empty list and raises:

    ValueError: No basis states found in the basis state directory.
    Please check that the basis_state_dir exists and contains the
    correct files with the correct extension.

The error gives no hint that the layout is wrong.

## Reproduction

    # Flat layout (intuitive but wrong):
    basis_state_dir/
        state.pdb       ← not found

    # Required layout (undocumented):
    basis_state_dir/
        00/
            state.pdb   ← found

## Proposed fix A — improved error message

In `_glob_basis_states()`, detect flat PDB files and emit a clear error:

    if not sim_input_dirs:
        flat = list(self.basis_state_dir.glob(f'*{self.basis_state_ext}'))
        if flat:
            raise ValueError(
                f'Found {len(flat)} PDB file(s) directly in '
                f'{self.basis_state_dir} but BasisStates expects each '
                f'basis state in its own subdirectory. '
                f'Required layout: basis_state_dir/00/state.pdb'
            )

## Proposed fix B — accept both flat and subdir layouts

Fall back to flat when no subdirectories are found.

## Proposed fix C — documentation only

Add a clear docstring paragraph and YAML comment explaining the
required layout.

## Context

Also: the CDK9 example's `03_equilibrate.py` (and `00_minimal_basis.py`)
save flat files by default and need updating to write the subdir layout.

Fix branch: `ndjones:bugfix/no-issue-basis-states-subdir-layout`
(implements fix A + improves field description and docstring)

File issue at: https://github.com/ramanathanlab/deepdrivewe-academy/issues/new
PR compare URL: https://github.com/ramanathanlab/deepdrivewe-academy/compare/develop...ndjones:deepdrivewe-academy:bugfix/no-issue-basis-states-subdir-layout

Environment: Python 3.11, macOS, deepdrivewe develop
```

---

## Issue C — ~~`LocalConfig`/`WorkstationConfig` use `address='localhost'`~~ RESOLVED UPSTREAM

> **Status: RESOLVED in `ramanathanlab/deepdrivewe-academy:develop`**
> before this issue was filed.  Confirmed by audit of
> `deepdrivewe/parsl.py` on `develop` (April 2026).
>
> `LocalConfig` uses `address='127.0.0.1'` (hardcoded).
> `WorkstationConfig` exposes `address: str = Field(default='127.0.0.1')`
> — configurable, defaults to the correct literal IP.
>
> Our local branch has been synced to the upstream version via:
>
>     git checkout origin/develop -- deepdrivewe/parsl.py
>
> No action required.  Body retained for historical reference only.

---

## Issue D — `LocalExchangeFactory + ParslPoolExecutor` raises `PicklingError`; example pattern broken

**Title:**
> `LocalExchangeFactory` + `ParslPoolExecutor` fails with `PicklingError`;
> example `main.py` pattern broken

**Labels:** `bug`, `examples`

**Body:**
```
## Summary

Passing `ParslPoolExecutor(parsl_config)` to
`Manager.from_exchange_factory` while also using
`LocalExchangeFactory` (the default) fails immediately with:

    _pickle.PicklingError: LocalExchangeFactory is not pickleable.

This affects the reference example `examples/openmm_ntl9_hk/main.py`
and would affect any new example that follows the same pattern.

## Reproduction

    async with await Manager.from_exchange_factory(
        factory=LocalExchangeFactory(),
        executors=ParslPoolExecutor(parsl_config),  # ← breaks
    ) as manager:
        ...
    # raises: _pickle.PicklingError: LocalExchangeFactory is not pickleable.

## Root cause

`LocalExchangeFactory` is built on shared in-process memory (Python
objects in the same address space). `ParslPoolExecutor` spawns a
separate subprocess via `HighThroughputExecutor` and must serialise
the agent (including its `Handle[WestpaAgent]` referencing the factory)
via `dill`. `LocalExchangeFactory` intentionally raises `PicklingError`
(see `academy/serialize.py`) because cross-process serialisation would
silently break in-process queue semantics.

## Affected files

As of April 2026 audit of `ramanathanlab/deepdrivewe-academy:develop`:

- `examples/openmm_ntl9_hk/main.py` — uses
  `executors=ParslPoolExecutor(parsl_config)` with the default
  `LocalExchangeFactory()` exchange.  Will fail at runtime with
  `PicklingError` on any machine that runs it with `--exchange local`.

## Valid combinations

| Exchange              | Executor          | Works? |
|-----------------------|-------------------|--------|
| LocalExchangeFactory  | executors=None    | ✓      |
| LocalExchangeFactory  | ThreadPoolExecutor| ✓      |
| LocalExchangeFactory  | ParslPoolExecutor | ✗      |
| HttpExchangeFactory   | ParslPoolExecutor | ✓      |

## Proposed fix — guard on exchange type

In `main.py`, select the executor based on the exchange type:

    if args.exchange == 'local':
        executor = None   # agents run as asyncio tasks in-process;
                          # blocking MD runs in agent_run_sync thread
    else:
        parsl_config = cfg.compute_config.get_parsl_config(
            output_dir / 'run-info')
        executor = ParslPoolExecutor(parsl_config)

    async with await Manager.from_exchange_factory(
        factory=create_exchange_factory(args.exchange),
        executors=executor,
    ) as manager:
        await run_westpa_workflow(...)

For local execution, `agent_run_sync()` inside each
`SimulationAgent.simulate()` already offloads blocking MD to a thread
pool, so `executors=None` does not block the event loop.

This fix has been applied in the CDK9/CyclinT1 example
(`examples/openmm_cdk9_cyclinT1/main.py`) on the
`ndjones/deepdrivewe-academy:feature/add-openmm-cdk9-cyclinT1-example`
branch.

Fix branch for NTL9: `ndjones:bugfix/no-issue-local-exchange-parsl-guard`
(guards `ParslPoolExecutor` behind `--exchange local` check in
`examples/openmm_ntl9_hk/main.py`)

File issue at: https://github.com/ramanathanlab/deepdrivewe-academy/issues/new
PR compare URL: https://github.com/ramanathanlab/deepdrivewe-academy/compare/develop...ndjones:deepdrivewe-academy:bugfix/no-issue-local-exchange-parsl-guard

Environment: Python 3.11, macOS (Apple M-series), deepdrivewe develop
```

---

## Issue E — `float('inf')` serialises to `null` in JSON via Pydantic

**Title:**
> `InferenceConfig` bin edge lists: `float('inf')` serialises to `null`
> in JSON (Pydantic v2)

**Labels:** `bug`, `low priority`

**Body:**
```
## Summary

Bin edge fields in `InferenceConfig` (and anywhere `list[float]` includes
`float('inf')`) serialise to `null` when `model.model_dump_json()` is
called, because Pydantic v2 maps `float('inf')` to JSON `null`.

    from pydantic import BaseModel
    class C(BaseModel):
        edges: list[float]
    print(C(edges=[1.0, float('inf')]).model_dump_json())
    # {"edges":[1.0,null]}   ← inf becomes null

YAML round-trips work correctly (`.inf` is a valid YAML float).

## Impact

Any code that saves or reads configs via JSON (e.g. config archival,
REST API, experiment tracking) will silently lose the `inf` sentinel,
causing `MultiRectilinearBinner` to fail on the next load.

## Proposed fix — field_serializer

    from pydantic import field_serializer
    import math

    class InferenceConfig(BaseModel):
        rmsd_bin_edges: list[float]
        salt_bridge_bin_edges: list[float]
        ...

        @field_serializer('rmsd_bin_edges', 'salt_bridge_bin_edges')
        def serialize_edges(self, v: list[float]) -> list:
            return ['inf' if math.isinf(x) else x for x in v]

## Context

Discovered during CDK9 example validation.  Does not block current
workflows (YAML is the primary config format) but will affect any future
JSON-based config serialization.
```

---

## Status

| Issue | Title | Status | Action |
|-------|-------|--------|--------|
| A | `stream.py` missing | **Resolved upstream** (`a71d92b`) — do not file | Remove stub from CDK9 branch |
| B | `BasisStates` subdir layout | **Open** — file issue + open PR | [File issue](https://github.com/ramanathanlab/deepdrivewe-academy/issues/new) · [PR compare](https://github.com/ramanathanlab/deepdrivewe-academy/compare/develop...ndjones:deepdrivewe-academy:bugfix/no-issue-basis-states-subdir-layout) |
| C | `address='localhost'` macOS | **Resolved upstream** — do not file | — |
| D | `LocalExchangeFactory + Parsl` | **Open** — file issue + open PR | [File issue](https://github.com/ramanathanlab/deepdrivewe-academy/issues/new) · [PR compare](https://github.com/ramanathanlab/deepdrivewe-academy/compare/develop...ndjones:deepdrivewe-academy:bugfix/no-issue-local-exchange-parsl-guard) |
| E | `float('inf')` JSON null | **Open (low priority)** — documented only | — |

Last audit: April 2026 against `ramanathanlab/deepdrivewe-academy:develop`.
