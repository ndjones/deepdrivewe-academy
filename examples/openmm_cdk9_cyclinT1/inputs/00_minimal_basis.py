"""Create minimal basis states for smoke-testing (no NVT equilibration).

Skips the 2 ns NVT run in 03_equilibrate.py.  Runs only energy
minimisation and saves a single basis_000.pdb for each condition.

Usage (from the inputs/ directory):
    python 00_minimal_basis.py

This is intentionally NOT a substitute for proper equilibration.
Use 03_equilibrate.py for any science.  This script exists solely
to produce valid OpenMM restart PDBs for CI / smoke testing.
"""

from __future__ import annotations

from pathlib import Path

from openmm import LangevinMiddleIntegrator
from openmm import Platform
from openmm import unit
from openmm.app import ForceField
from openmm.app import Modeller
from openmm.app import PDBFile
from openmm.app import Simulation

HERE = Path(__file__).parent

CONDITIONS = {
    'apo': HERE / 'apo' / 'cdk9_apo_clean.pdb',
    'holo_cyclinT1': HERE / 'holo_cyclinT1' / 'cdk9_holo_cyclinT1_clean.pdb',
}

FORCEFIELD_FILES = ['amber14-all.xml', 'implicit/gbn2.xml']


def make_basis(condition: str, clean_pdb: Path) -> None:
    """Energy-minimise clean_pdb and save as basis_000.pdb.

    The BasisStates API (deepdrivewe.api.BasisStates._glob_basis_states)
    expects subdirectories inside basis_state_dir, each containing one
    PDB file.  We create: <condition>/00/basis_000.pdb so that
    basis_state_dir=inputs/<condition> works correctly.
    """
    # Write into a numbered subdirectory (API requires subdir structure)
    out_dir = clean_pdb.parent / '00'
    out_dir.mkdir(exist_ok=True)
    out_pdb = out_dir / 'basis_000.pdb'

    print(f'\n[{condition}] Loading {clean_pdb.name}')
    pdb = PDBFile(str(clean_pdb))

    ff = ForceField(*FORCEFIELD_FILES)

    print(f'[{condition}] Adding hydrogens ...')
    modeller = Modeller(pdb.topology, pdb.positions)
    modeller.addHydrogens(ff)

    system = ff.createSystem(modeller.topology)

    integrator = LangevinMiddleIntegrator(
        300 * unit.kelvin,
        1.0 / unit.picoseconds,
        0.002 * unit.picoseconds,
    )

    try:
        platform = Platform.getPlatformByName('CPU')
    except Exception:
        platform = Platform.getPlatformByName('Reference')

    sim = Simulation(modeller.topology, system, integrator, platform)
    sim.context.setPositions(modeller.positions)

    print(f'[{condition}] Energy minimising ...')
    sim.minimizeEnergy(maxIterations=500)
    print(f'[{condition}] Done.  Writing {out_pdb.name}')

    state = sim.context.getState(getPositions=True)
    with open(out_pdb, 'w') as f:
        PDBFile.writeFile(modeller.topology, state.getPositions(), f)
    print(f'[{condition}] Saved → {out_pdb}')


if __name__ == '__main__':
    for cond, pdb_path in CONDITIONS.items():
        if not pdb_path.exists():
            print(f'SKIP {cond}: {pdb_path} not found — run 01_download_and_clean.py first')
            continue
        make_basis(cond, pdb_path)
    print('\nDone.  Run 04_verify_pcoord_residues.py to confirm residue numbering.')
