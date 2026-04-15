"""CDK9 / CyclinT1 WestpaAgent for Phase 1 weighted ensemble.

CDK9WestpaAgent
---------------
Subclasses WestpaAgent and implements run_inference() with:

  - MultiRectilinearBinner  — 2D grid over (RMSD, salt-bridge).
  - HighRecycler            — recycles walkers where RMSD > threshold.
  - HuberKimResampler       — merge/split within each bin cell.

In Phase 1 there are no goal-directed reward signals; the only
objective is uniform exploration of the (RMSD, salt-bridge) 2D
space.  run_inference() logs the αC-in fraction (salt-bridge < 4 Å)
each iteration for monitoring purposes only.

Phase 4 extension point
-----------------------
When reward-based guidance is added:
1. Subclass CDK9WestpaAgent or add a @loop to it.
2. Adjust bin_target_counts per bin based on goal proximity.
3. Emit reward signals to steer walker allocation toward goal cells.

See CLAUDE.md for the full phased roadmap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from deepdrivewe.api import BaseModel
from deepdrivewe.api import IterationMetadata
from deepdrivewe.api import SimMetadata
from deepdrivewe.api import SimResult
from deepdrivewe.binners.multirectilinear import MultiRectilinearBinner
from deepdrivewe.checkpoint import EnsembleCheckpointer
from deepdrivewe.recyclers.high import HighRecycler
from deepdrivewe.resamplers import HuberKimResampler
from deepdrivewe.workflows.westpa import SimulationAgent
from deepdrivewe.workflows.westpa import WestpaAgent

if TYPE_CHECKING:
    from academy.handle import Handle
    from deepdrivewe.api import WeightedEnsemble


# ---------------------------------------------------------------------------
# Inference configuration
# ---------------------------------------------------------------------------


class InferenceConfig(BaseModel):
    """Configuration for CDK9 WE inference (binner + resampler + recycler).

    Parameters
    ----------
    rmsd_bin_edges : list[float]
        Bin edges for pcoord[0] (Cα RMSD, Å).
    salt_bridge_bin_edges : list[float]
        Bin edges for pcoord[1] (salt-bridge distance, Å).
    sims_per_bin : int
        Target walker count per 2D bin cell.
    max_allowed_weight : float
        Maximum walker weight before splitting.
    min_allowed_weight : float
        Minimum walker weight before merging.
    rmsd_boundary_ang : float
        RMSD threshold (Å) above which walkers are recycled to basis
        states.  Prevents unfolded walkers from persisting.
    """

    rmsd_bin_edges: list[float] = Field(
        default=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, float('inf')],
        description='Bin edges for pcoord[0] (Cα RMSD, Å).',
    )
    salt_bridge_bin_edges: list[float] = Field(
        default=[
            0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0,
            14.0, 16.0, 18.0, 20.0, float('inf'),
        ],
        description='Bin edges for pcoord[1] (salt-bridge distance, Å).',
    )
    sims_per_bin: int = Field(
        default=4,
        ge=1,
        description='Target walker count per 2D bin cell.',
    )
    max_allowed_weight: float = Field(
        default=0.25,
        description='Maximum walker weight before splitting.',
    )
    min_allowed_weight: float = Field(
        default=1e-40,
        description='Minimum walker weight before merging.',
    )
    rmsd_boundary_ang: float = Field(
        default=6.0,
        description=(
            'Cα RMSD threshold (Å) above which walkers are recycled.'
        ),
    )


# ---------------------------------------------------------------------------
# CDK9 WestpaAgent
# ---------------------------------------------------------------------------


class CDK9WestpaAgent(WestpaAgent):
    """WestpaAgent with CDK9-specific 2D binning and RMSD recycling.

    Implements run_inference() using:
    - MultiRectilinearBinner over (RMSD × salt-bridge) 2D space.
    - HighRecycler to recycle walkers with RMSD > rmsd_boundary_ang.
    - HuberKimResampler for merge/split within each bin cell.

    Also logs the αC-in fraction (pcoord[1] < 4 Å) each iteration as
    a monitoring metric (no effect on sampling).
    """

    def __init__(
        self,
        simulation_handles: list[Handle[SimulationAgent]],
        max_iterations: int,
        ensemble: WeightedEnsemble,
        checkpointer: EnsembleCheckpointer | None = None,
        inference_config: InferenceConfig | None = None,
    ) -> None:
        super().__init__(
            simulation_handles=simulation_handles,
            max_iterations=max_iterations,
            ensemble=ensemble,
            checkpointer=checkpointer,
        )
        self.inference_config = (
            inference_config if inference_config is not None
            else InferenceConfig()
        )

    def run_inference(
        self,
        sim_results: list[SimResult],
    ) -> tuple[list[SimMetadata], list[SimMetadata], IterationMetadata]:
        """Apply 2D binning, RMSD recycling, and Huber-Kim resampling.

        Parameters
        ----------
        sim_results : list[SimResult]
            Completed simulation results from the current iteration.

        Returns
        -------
        tuple
            (next_sims, recycled_sims, iteration_metadata) as required
            by the WestpaAgent ABC.
        """
        cfg = self.inference_config

        # --- Monitoring: log αC-in fraction (salt-bridge < 4 Å) ---
        pcoords_last = [r.metadata.pcoord[-1] for r in sim_results]
        sb_values = [
            p[1] for p in pcoords_last if len(p) >= 2
        ]
        if sb_values:
            ac_in_frac = (
                sum(1 for v in sb_values if v < 4.0) / len(sb_values)
            )
            self.logger.info(
                f'[CDK9] walkers={len(sb_values)} '
                f'aC_in_frac={ac_in_frac:.2f} '
                f'(salt_bridge < 4 Å)',
            )

        cur_sims = [r.metadata for r in sim_results]

        binner = MultiRectilinearBinner(
            bins=[cfg.rmsd_bin_edges, cfg.salt_bridge_bin_edges],
            bin_target_counts=cfg.sims_per_bin,
        )

        assert self.basis_states is not None
        recycler = HighRecycler(
            basis_states=self.basis_states,
            target_threshold=cfg.rmsd_boundary_ang,
            pcoord_idx=0,
        )

        resampler = HuberKimResampler(
            sims_per_bin=cfg.sims_per_bin,
            max_allowed_weight=cfg.max_allowed_weight,
            min_allowed_weight=cfg.min_allowed_weight,
        )

        return resampler.run(cur_sims, binner, recycler)
