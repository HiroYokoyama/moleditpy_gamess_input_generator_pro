"""Everything the README claims, and the job GAMESS really ran for each.

A job name is a key of tests/verified_jobs.py and a file in tests/verified_inputs.
What the window does with those claims is in tests/test_real_dialog.py.
"""

CLAIMS = {
    "RHF": "rhf_energy",
    "UHF": "uhf_triplet",
    "ROHF": "rohf_triplet",
    "DFT optimization": "b3lyp_opt",
    "gradient": "gradient",
    "Hessian": "hessian",
    "saddle point with a computed Hessian": "sadpoint",
    "MP2": "mp2",
    "CCSD(T) with MEMDDI": "ccsd_t",
    "TD-DFT": "tddft",
    "NMR on one core": "nmr",
    "PCM": "pcm",
    "SMD": "smd",
    "D3": "d3",
    "D3(BJ)": "d3bj",
    "Raman with $HESS and $DIPDR in Extra Groups": "raman",
    "optimization from a read $HESS": "hess_read",
    "start from $VEC with MOREAD": "moread",
    "minimal basis": "basis_sto",
    "Pople basis with polarization and diffuse functions": "basis_n311",
    "PCseg basis with automatic ISPHER": "basis_pcseg",
    "augmented correlation-consistent basis with automatic ISPHER": "basis_acc",
    "Z-matrix": "zmatrix",
    "Z-matrix optimization": "zmatrix_opt",
    "Z-matrix with variables": "zmatrix_variables",
    "Z-matrix in Bohr": "zmatrix_bohr",
    "ghost atom with its basis (negative ZNUC)": "ghost",
    "plain dummy atom (ZNUC 0)": "ghost_plain",
    "UNITS=BOHR": "units_bohr",
    "fitted ESP charges": "esp",
    "every orbital printed (NPRINT=7)": "print_orbitals",
    "cation": "cation",
    "anion": "anion",
    "$STATPT, $SCF and $GUESS options": "job_options",
    "guessed starting Hessian": "hess_guess",
    "analytic Hessian": "hess_analytic",
    "seminumerical Hessian": "hess_seminum",
    "fully numerical Hessian": "hess_fullnum",
    "Huckel guess": "guess_huckel",
}

# The warning shown for each job GAMESS refuses, and what GAMESS itself prints.
REFUSALS = {
    "refuse_rhf_triplet": ("needs MULT=1", "SCFTYP=RHF MUST HAVE MULT=1"),
    "refuse_bad_parity": (
        "cannot have multiplicity",
        "CHECK YOUR INPUT CHARGE AND MULTIPLICITY",
    ),
    "refuse_cc_no_memddi": ("needs MEMDDI", "INSUFFICIENT DISTRIBUTED MEMORY"),
    "refuse_lccd_parallel": (
        "one core only",
        "ONLY CCTYP=CCSD OR CCTYP=CCSD(T) CAN RUN IN PARALLEL",
    ),
    "refuse_cc_with_dft": ("at most one", "AT MOST ONE CORRELATION METHOD"),
    "refuse_mp2_with_dft": ("at most one", "AT MOST ONE CORRELATION METHOD"),
    "refuse_mp2_with_cc": ("at most one", "AT MOST ONE CORRELATION METHOD"),
    "refuse_nmr_dft": (
        "works only with RHF",
        "INCOMPATIBLE OPTION CHOSEN WITH RUNTYP=NMR",
    ),
    "refuse_nmr_uhf": (
        "works only with RHF",
        "INCOMPATIBLE OPTION CHOSEN WITH RUNTYP=NMR",
    ),
    "refuse_nmr_dirscf": (
        "does not work with DIRSCF",
        "INCOMPATIBLE OPTION CHOSEN WITH RUNTYP=NMR",
    ),
    "refuse_nmr_parallel": ("one core", "INCOMPATIBLE OPTION CHOSEN WITH RUNTYP=NMR"),
    "refuse_pcseg_cartesian": ("needs ISPHER=1", "PLEASE SET ISPHER=1"),
    "refuse_sadpoint_no_hess": ("HESS=CALC", "DID NOT SUPPLY A $HESS GROUP"),
    "refuse_raman_no_hess": ("needs $HESS and $DIPDR", "RAMAN SPECTRUM REQUIRES"),
}
