"""Entry point for CDK9 / CyclinT1 Phase 1 weighted ensemble.

Usage
-----
Run from the deepdrivewe-academy repository root:

    python examples/openmm_cdk9_cyclinT1/main.py \\
        --config examples/openmm_cdk9_cyclinT1/config_apo.yaml

    python examples/openmm_cdk9_cyclinT1/main.py \\
        --config examples/openmm_cdk9_cyclinT1/config_holo_cyclinT1.yaml

With the Academy Exchange Cloud (Globus):

    python examples/openmm_cdk9_cyclinT1/main.py \\
        --config examples/openmm_cdk9_cyclinT1/config_apo.yaml \\
        --exchange globus

Prerequisites
-------------
1. Install deepdrivewe-academy:  pip install -e .
2. Run the structure preparation pipeline:
       cd examples/openmm_cdk9_cyclinT1/inputs
       python 01_download_and_clean.py
       python 03_equilibrate.py      # ~3-5 h on CPU; use HPC scripts
       python 04_verify_pcoord_residues.py
3. Edit the YAML config: set compute_config, output_dir.

Agent topology
--------------
::

    CDK9WestpaAgent
    ├── CDK9SimulationAgent (worker 0)
    ├── CDK9SimulationAgent (worker 1)
    └── CDK9SimulationAgent (worker N)

    CDK9WestpaAgent.run_inference():
        binner:    MultiRectilinearBinner (2D RMSD × salt-bridge)
        resampler: HuberKimResampler
        recycler:  HighRecycler (RMSD > threshold → recycle)

See CLAUDE.md for architecture overview and design decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import MDAnalysis
import numpy as np
from MDAnalysis.analysis import rms

# Allow running as a script from the repo root without installing the
# example as a package.
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from academy.exchange.cloud.client import HttpExchangeFactory
from academy.exchange.local import LocalExchangeFactory
from academy.logging import init_logging
from academy.manager import Manager
from parsl.concurrent import ParslPoolExecutor
from pydantic import Field
from pydantic import field_validator

from deepdrivewe.api import BaseModel
from deepdrivewe.api import BasisStates
from deepdrivewe.api import SimMetadata  # noqa: F401 (re-exported)
from deepdrivewe.api import TargetState
from deepdrivewe.api import WeightedEnsemble
from deepdrivewe.checkpoint import EnsembleCheckpointer
from deepdrivewe.parsl import ComputeConfigTypes
from deepdrivewe.workflows.westpa import run_westpa_workflow

from orchestrator import CDK9WestpaAgent
from orchestrator import InferenceConfig
from simulate import CDK9SimulationAgent
from simulate import SimulationConfig

EXCHANGE_ADDRESS = 'https://exchange.academy-agents.org'


# ---------------------------------------------------------------------------
# Basis state pcoord initializer
# ---------------------------------------------------------------------------


class CDK9BasisStateInitializer(BaseModel):
    """Compute the 2D pcoord for each basis state PDB file.

    Returns [rmsd, salt_bridge_dist] so that the WeightedEnsemble
    assigns initial walkers to the correct 2D bin.

    Parameters
    ----------
    reference_file : Path
        Reference PDB for Cα RMSD superposition (typically
        basis_000.pdb).
    mda_selection : str
        MDAnalysis atom selection for the RMSD calculation.
    chain : str
        Chain ID containing Glu66 and Lys48 (CDK9 = 'A').
    glu66_resnum : int
        Residue sequence number of Glu66 (default 66).
    lys48_resnum : int
        Residue sequence number of Lys48 (default 48).
    """

    reference_file: Path = Field(
        description='Reference PDB for Cα RMSD superposition.',
    )
    mda_selection: str = Field(
        default='protein and name CA',
        description='MDAnalysis atom selection for RMSD.',
    )
    chain: str = Field(
        default='A',
        description='Chain ID for Glu66/Lys48 (CDK9 = A).',
    )
    glu66_resnum: int = Field(
        default=66,
        description='Residue sequence number of Glu66.',
    )
    lys48_resnum: int = Field(
        default=48,
        description='Residue sequence number of Lys48.',
    )

    def __call__(self, basis_file: str) -> list[float]:
        """Return [rmsd, salt_bridge_dist] for a single basis state.

        Parameters
        ----------
        basis_file : str
            Path to the basis state PDB file.

        Returns
        -------
        list[float]
            [pcoord[0], pcoord[1]] = [Cα RMSD (Å), Glu66–Lys48 (Å)].
        """
        u = MDAnalysis.Universe(basis_file)
        ref = MDAnalysis.Universe(str(self.reference_file))

        # pcoord[0]: Cα RMSD
        pos = u.select_atoms(self.mda_selection).positions
        ref_pos = ref.select_atoms(self.mda_selection).positions
        rmsd_val: float = rms.rmsd(pos, ref_pos, superposition=True)

        # pcoord[1]: Glu66 CD – Lys48 NZ salt-bridge distance
        sel_glu = (
            f'(segid {self.chain} or chainID {self.chain}) '
            f'and resnum {self.glu66_resnum} and name CD'
        )
        sel_lys = (
            f'(segid {self.chain} or chainID {self.chain}) '
            f'and resnum {self.lys48_resnum} and name NZ'
        )
        glu_atoms = u.select_atoms(sel_glu)
        lys_atoms = u.select_atoms(sel_lys)

        if len(glu_atoms) == 0 or len(lys_atoms) == 0:
            print(
                f'WARNING: CDK9BasisStateInitializer: '
                f'Glu{self.glu66_resnum} CD or '
                f'Lys{self.lys48_resnum} NZ not found in '
                f'{basis_file}. Setting pcoord[1] = NaN.',
                flush=True,
            )
            salt_bridge_dist: float = float('nan')
        else:
            salt_bridge_dist = float(
                np.linalg.norm(
                    glu_atoms.positions[0] - lys_atoms.positions[0]
                )
            )

        return [rmsd_val, salt_bridge_dist]


# ---------------------------------------------------------------------------
# Experiment settings
# ---------------------------------------------------------------------------


class ExperimentSettings(BaseModel):
    """Full configuration for one CDK9 WE condition (apo or holo).

    Loaded from YAML via ExperimentSettings.from_yaml(path).
    """

    output_dir: Path = Field(
        description='Root output directory for this run.',
    )
    num_iterations: int = Field(
        ge=1,
        description='Number of weighted ensemble iterations to run.',
    )
    basis_states: BasisStates = Field(
        description='Basis state configuration (dir, extension, count).',
    )
    basis_state_initializer: CDK9BasisStateInitializer = Field(
        description='Computes initial pcoord for each basis state.',
    )
    target_states: list[TargetState] = Field(
        default=[],
        description=(
            'Target states for recycling.  CDK9 Phase 1 uses no '
            'target states; HighRecycler handles the RMSD boundary.'
        ),
    )
    simulation_config: SimulationConfig = Field(
        description='OpenMM simulation parameters (includes openmm_config).',
    )
    inference_config: InferenceConfig = Field(
        description='Binner, resampler, and recycler parameters.',
    )
    compute_config: ComputeConfigTypes = Field(
        description='Parsl compute configuration for running simulations.',
    )

    @field_validator('output_dir')
    @classmethod
    def mkdir_validator(cls, value: Path) -> Path:
        """Resolve and create the output directory."""
        value = value.resolve()
        value.mkdir(parents=True, exist_ok=True)
        return value


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _export_pythonpath() -> None:
    """Add this directory to PYTHONPATH for Parsl workers."""
    example_dir = str(Path(__file__).resolve().parent)
    pythonpath = os.environ.get('PYTHONPATH', '')
    if example_dir not in pythonpath:
        os.environ['PYTHONPATH'] = example_dir + os.pathsep + pythonpath


def create_exchange_factory(
    exchange_type: str,
) -> LocalExchangeFactory | HttpExchangeFactory:
    """Create the Academy exchange factory.

    Parameters
    ----------
    exchange_type : str
        'local' for in-process communication or 'globus' for the
        Academy Exchange Cloud.
    """
    if exchange_type == 'local':
        return LocalExchangeFactory()
    return HttpExchangeFactory(url=EXCHANGE_ADDRESS, auth_method='globus')


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = ArgumentParser(
        description='CDK9/CyclinT1 Phase 1 weighted ensemble',
    )
    parser.add_argument(
        '-c',
        '--config',
        required=True,
        help='Path to YAML config (config_apo.yaml or '
        'config_holo_cyclinT1.yaml)',
    )
    parser.add_argument(
        '--exchange',
        choices=['local', 'globus'],
        default='local',
        help='Academy exchange backend (default: local)',
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the CDK9 Phase 1 weighted ensemble workflow."""
    _export_pythonpath()
    args = parse_args()
    cfg = ExperimentSettings.from_yaml(args.config)
    cfg.dump_yaml(cfg.output_dir / 'params.yaml')

    init_logging('INFO', logfile=cfg.output_dir / 'runtime.log')

    checkpointer = EnsembleCheckpointer(output_dir=cfg.output_dir)
    checkpoint = checkpointer.latest_checkpoint()

    if checkpoint is None:
        ensemble = WeightedEnsemble(
            basis_states=cfg.basis_states,
            target_states=cfg.target_states,
        )
        ensemble.initialize_basis_states(cfg.basis_state_initializer)
    else:
        ensemble = checkpointer.load(checkpoint)
        logging.info(f'Loaded ensemble from checkpoint {checkpoint}')

    # Shared kwargs for run_westpa_workflow regardless of exchange type.
    workflow_kwargs = {
        'manager': None,  # filled in below
        'sim_agent_type': CDK9SimulationAgent,
        'westpa_agent_type': CDK9WestpaAgent,
        'max_iterations': cfg.num_iterations,
        'ensemble': ensemble,
        'checkpointer': checkpointer,
        'sim_agent_kwargs': {
            'sim_config': cfg.simulation_config,
            'output_dir': cfg.output_dir / 'simulation',
        },
        'westpa_agent_kwargs': {
            'inference_config': cfg.inference_config,
        },
        'westpa_executor': 'cpu',
        'logfile': cfg.output_dir / 'runtime.log',
    }

    if args.exchange == 'local':
        # LocalExchangeFactory uses shared in-process memory and cannot
        # be serialised by ParslPoolExecutor (cross-process). Run agents
        # as asyncio tasks with a CPU thread-pool executor instead.
        # Blocking MD is offloaded to a thread inside run_simulation().
        async with await Manager.from_exchange_factory(
            factory=create_exchange_factory(args.exchange),
            executors={'cpu': ThreadPoolExecutor(max_workers=1)},
            default_executor='cpu',
        ) as manager:
            await run_westpa_workflow(
                **{**workflow_kwargs, 'manager': manager},
                sim_executor='cpu',
            )
    else:
        # Cross-process exchange: dispatch simulations to GPU workers
        # via Parsl, keep the WestpaAgent on a CPU thread.
        parsl_config = cfg.compute_config.get_parsl_config(
            cfg.output_dir / 'run-info',
        )

        # Create the Parsl executor outside the Manager context so we
        # can guarantee cleanup even if the process is interrupted.
        gpu_executor = ParslPoolExecutor(parsl_config)

        # Handle `kill <pid>` (SIGTERM). Parsl workers survive the main
        # process dying, and normal interpreter shutdown hangs after
        # atexit cleans up the DFK. Using os._exit() after shutdown
        # sidesteps the hang while still tearing down workers cleanly.
        def _handle_sigterm(*_: object) -> None:
            gpu_executor.shutdown(wait=False)
            os._exit(0)

        signal.signal(signal.SIGTERM, _handle_sigterm)

        try:
            async with await Manager.from_exchange_factory(
                factory=create_exchange_factory(args.exchange),
                executors={
                    'gpu': gpu_executor,
                    'cpu': ThreadPoolExecutor(max_workers=1),
                },
                default_executor='gpu',
            ) as manager:
                await run_westpa_workflow(
                    **{**workflow_kwargs, 'manager': manager},
                    sim_executor='gpu',
                )
        finally:
            gpu_executor.shutdown(wait=False)


if __name__ == '__main__':
    asyncio.run(main())
