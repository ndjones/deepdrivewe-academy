"""CDK9 / CyclinT1 simulation components for Phase 1 weighted ensemble.

Progress coordinate layout
--------------------------
pcoord[0]  Cα RMSD to the reference PDB (Angstrom).
           Measures global structural drift; walkers that exceed
           RMSD_BOUNDARY_ANG are recycled to basis states (see
           orchestrator.py InferenceConfig.rmsd_boundary_ang).

pcoord[1]  Glu66 Cδ (CD) – Lys48 Nζ (NZ) Euclidean distance (Angstrom).
           Reports the αC-helix salt-bridge status:
             ~3.5 Å  → αC-in  (active / DFG-in)
             > 8 Å   → αC-out (inactive / intermediate)

Both components are computed at each reporter step and stored on
SimMetadata.pcoord as a (n_frames, 2) array per simulation segment.

Relationship to deepdrivewe
---------------------------
CDK9PcoordReporter  subclasses ContactMapRMSDReporter.
  - Inherits Cα contact-map collection (kept for Phase 2 CVAE).
  - Overrides report() to also compute the Glu66–Lys48 distance.
  - Overrides get_rmsds() to return shape (n_frames, 2).

CDK9SimulationAgent  subclasses SimulationAgent (new API).
  - Sync run_simulation() — framework offloads to thread pool.
  - Injects CDK9PcoordReporter instead of ContactMapRMSDReporter.

SimulationConfig  wraps OpenMMConfig with CDK9-specific reporter
  fields (glu_resnum, lys_resnum, chain_id).

See CLAUDE.md for design rationale.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from academy.handle import Handle
from pydantic import Field
from pydantic import field_validator

from deepdrivewe.api import BaseModel
from deepdrivewe.api import SimMetadata
from deepdrivewe.api import SimResult
from deepdrivewe.api import validate_and_resolve_file
from deepdrivewe.simulation.openmm import ContactMapRMSDReporter
from deepdrivewe.simulation.openmm import OpenMMConfig
from deepdrivewe.simulation.openmm import OpenMMSimulation
from deepdrivewe.workflows.westpa import SimulationAgent
from deepdrivewe.workflows.westpa import WestpaAgent

try:
    import openmm
    from openmm import app
except ImportError:
    pass  # Handled at runtime


# ---------------------------------------------------------------------------
# Simulation configuration
# ---------------------------------------------------------------------------


class SimulationConfig(BaseModel):
    """OpenMM simulation configuration for the CDK9 WE example.

    Mirrors the NTL9 SimulationConfig but adds CDK9-specific fields
    for the salt-bridge reporter.

    Parameters
    ----------
    openmm_config : OpenMMConfig
        Core OpenMM parameters (timestep, temperature, platform, …).
    reference_file : Path
        Reference PDB for Cα RMSD superposition.
    cutoff_angstrom : float
        Contact-map cutoff distance (Å).
    mda_selection : str
        MDAnalysis atom selection for RMSD / contact map.
    openmm_selection : list[str]
        OpenMM atom names for RMSD / contact map.
    glu_resnum : int
        Residue number of Glu66 in CDK9 (default 66).
    lys_resnum : int
        Residue number of Lys48 in CDK9 (default 48).
    chain_id : str
        Chain identifier containing both residues (default 'A').
    """

    openmm_config: OpenMMConfig = Field(
        description='Core OpenMM simulation parameters.',
    )
    reference_file: Path = Field(
        description='Reference PDB for RMSD / contact map calculation.',
    )
    cutoff_angstrom: float = Field(
        default=8.0,
        description='Contact map cutoff distance (Å).',
    )
    mda_selection: str = Field(
        default='protein and name CA',
        description='MDAnalysis selection for RMSD / contact map.',
    )
    openmm_selection: list[str] = Field(
        default=['CA'],
        description='OpenMM atom names for RMSD / contact map.',
    )
    glu_resnum: int = Field(
        default=66,
        description='Residue number of Glu66 (CDK9 αC-helix salt-bridge).',
    )
    lys_resnum: int = Field(
        default=48,
        description='Residue number of Lys48 (CDK9 αC-helix salt-bridge).',
    )
    chain_id: str = Field(
        default='A',
        description='Chain ID for Glu/Lys residues (CDK9 = A).',
    )

    @field_validator('reference_file')
    @classmethod
    def resolve_file(cls, value: Path) -> Path:
        """Validate and resolve the reference file path."""
        result = validate_and_resolve_file(value)
        assert result is not None
        return result


# ---------------------------------------------------------------------------
# CDK9 pcoord reporter
# ---------------------------------------------------------------------------


class CDK9PcoordReporter(ContactMapRMSDReporter):
    """Two-dimensional progress coordinate reporter for CDK9.

    Extends ContactMapRMSDReporter with a second pcoord dimension:
    the Glu66 CD – Lys48 NZ salt-bridge distance.  Contact maps are
    still accumulated so that CVAE analysis (Phase 2) can be added
    without re-running simulations.

    Parameters
    ----------
    report_interval : int
        Frames between reports (inherited).
    reference_file : Path
        Reference PDB for Cα RMSD superposition (inherited).
    cutoff_angstrom : float
        Contact-map cutoff in Angstrom (inherited, default 8 Å).
    mda_selection : str
        MDAnalysis atom selection for RMSD/contact map (inherited).
    openmm_selection : sequence of str
        OpenMM atom names for RMSD/contact map (inherited).
    glu_resnum : int
        Residue sequence number of Glu66 in chain A (default 66).
    lys_resnum : int
        Residue sequence number of Lys48 in chain A (default 48).
    chain_id : str
        Chain identifier for both residues (default 'A' = CDK9).
    """

    def __init__(
        self,
        report_interval: int,
        reference_file: Path,
        cutoff_angstrom: float = 8.0,
        mda_selection: str = 'protein and name CA',
        openmm_selection: tuple[str, ...] = ('CA',),
        glu_resnum: int = 66,
        lys_resnum: int = 48,
        chain_id: str = 'A',
    ) -> None:
        super().__init__(
            report_interval=report_interval,
            reference_file=reference_file,
            cutoff_angstrom=cutoff_angstrom,
            mda_selection=mda_selection,
            openmm_selection=openmm_selection,
        )
        self._glu_resnum = glu_resnum
        self._lys_resnum = lys_resnum
        self._chain_id = chain_id

        # Atom indices resolved lazily on first report() call.
        self._glu_cd_idx: int | None = None
        self._lys_nz_idx: int | None = None
        self._salt_bridge_indexed = False

        # Accumulated salt-bridge distances (one per report step).
        self._pcoord2: list[float] = []

    def _resolve_salt_bridge_indices(
        self,
        simulation: app.Simulation,
    ) -> None:
        """Identify Glu66 CD and Lys48 NZ atom indices from topology.

        Called once on the first report() invocation.  Index lookup is
        tolerant of insertion codes in residue IDs (tries int cast).
        """
        for atom in simulation.topology.atoms():
            res = atom.residue
            try:
                resnum = int(res.id)
            except ValueError:
                continue

            chain = res.chain.id

            if (
                chain == self._chain_id
                and resnum == self._glu_resnum
                and atom.name == 'CD'
            ):
                self._glu_cd_idx = atom.index
            elif (
                chain == self._chain_id
                and resnum == self._lys_resnum
                and atom.name == 'NZ'
            ):
                self._lys_nz_idx = atom.index

        if self._glu_cd_idx is None:
            print(
                f'WARNING: CDK9PcoordReporter: Glu{self._glu_resnum} CD '
                f'not found in chain {self._chain_id}. '
                f'pcoord[1] will be NaN.',
                flush=True,
            )
        if self._lys_nz_idx is None:
            print(
                f'WARNING: CDK9PcoordReporter: Lys{self._lys_resnum} NZ '
                f'not found in chain {self._chain_id}. '
                f'pcoord[1] will be NaN.',
                flush=True,
            )
        self._salt_bridge_indexed = True

    def report(
        self,
        simulation: app.Simulation,
        state: openmm.State,
    ) -> None:
        """Generate a two-dimensional pcoord report.

        Calls the parent to accumulate the contact map and Cα RMSD
        (pcoord[0]), then computes the salt-bridge distance (pcoord[1]).
        """
        # Parent handles contact map + RMSD accumulation.
        super().report(simulation, state)

        # Resolve atom indices once per simulation segment.
        if not self._salt_bridge_indexed:
            self._resolve_salt_bridge_indices(simulation)

        # Compute salt-bridge distance (nm → Angstrom).
        if (
            self._glu_cd_idx is not None
            and self._lys_nz_idx is not None
        ):
            positions = state.getPositions(asNumpy=True)
            glu_pos = positions[self._glu_cd_idx] * 10.0  # nm → Å
            lys_pos = positions[self._lys_nz_idx] * 10.0
            dist = float(
                np.linalg.norm(np.array(glu_pos) - np.array(lys_pos))
            )
        else:
            dist = float('nan')

        self._pcoord2.append(dist)

    def get_rmsds(self) -> np.ndarray:
        """Return the 2D progress coordinate array.

        Returns
        -------
        np.ndarray
            Shape (n_frames, 2): column 0 = Cα RMSD (Å),
            column 1 = Glu66 CD – Lys48 NZ distance (Å).
        """
        rmsd = np.array(self._rmsd)      # populated by parent report()
        sb = np.array(self._pcoord2)
        n = min(len(rmsd), len(sb))
        return np.column_stack([rmsd[:n], sb[:n]])


# ---------------------------------------------------------------------------
# CDK9 simulation agent
# ---------------------------------------------------------------------------


class CDK9SimulationAgent(SimulationAgent):
    """Simulation agent for CDK9 weighted ensemble.

    Subclasses SimulationAgent (new 2-agent API).  The sync
    run_simulation() method is offloaded to a thread pool by the
    parent's @action simulate().

    Identical to a standard OpenMM SimulationAgent except that
    CDK9PcoordReporter is injected to capture the 2D progress
    coordinate (RMSD + salt-bridge distance).

    Parameters
    ----------
    westpa_handle : Handle[WestpaAgent]
        Handle to the WestpaAgent (injected by run_westpa_workflow).
    sim_config : SimulationConfig
        CDK9 simulation configuration.
    output_dir : Path
        Root directory for per-segment simulation output.
    """

    def __init__(
        self,
        westpa_handle: Handle[WestpaAgent],
        sim_config: SimulationConfig,
        output_dir: Path,
    ) -> None:
        super().__init__(westpa_handle)
        self.sim_config = sim_config
        self.output_dir = output_dir

    def run_simulation(self, metadata: SimMetadata) -> SimResult:
        """Run one MD segment with the CDK9 2D pcoord reporter.

        Parameters
        ----------
        metadata : SimMetadata
            Metadata for this simulation segment (includes
            parent_restart_file and simulation_name).

        Returns
        -------
        SimResult
            data keys: 'contact_maps' (n_frames, n_atoms, n_atoms),
                       'pcoord'       (n_frames, 2).
        """
        metadata.mark_simulation_start()

        sim_output_dir = self.output_dir / metadata.simulation_name
        if sim_output_dir.exists():
            for f in sim_output_dir.iterdir():
                f.unlink()
        sim_output_dir.mkdir(parents=True, exist_ok=True)

        self.sim_config.dump_yaml(sim_output_dir / 'config.yaml')

        simulation = OpenMMSimulation(
            config=self.sim_config.openmm_config,
            output_dir=sim_output_dir,
            checkpoint_file=metadata.parent_restart_file,
        )

        reporter = CDK9PcoordReporter(
            report_interval=self.sim_config.openmm_config.report_steps,
            reference_file=self.sim_config.reference_file,
            cutoff_angstrom=self.sim_config.cutoff_angstrom,
            mda_selection=self.sim_config.mda_selection,
            openmm_selection=tuple(self.sim_config.openmm_selection),
            glu_resnum=self.sim_config.glu_resnum,
            lys_resnum=self.sim_config.lys_resnum,
            chain_id=self.sim_config.chain_id,
        )

        simulation.run(reporters=[reporter])

        pcoord = reporter.get_rmsds()          # (n_frames, 2)
        contact_maps = reporter.get_contact_maps()

        metadata.restart_file = simulation.restart_file
        metadata.pcoord = pcoord.tolist()
        metadata.mark_simulation_end()

        return SimResult(
            data={'contact_maps': contact_maps, 'pcoord': pcoord},
            metadata=metadata,
        )
