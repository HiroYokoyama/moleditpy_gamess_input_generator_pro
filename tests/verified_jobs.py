"""The jobs GAMESS really ran, written by the plugin's own group and card code.

tests/verified_inputs holds the rendered files and RESULTS.json what GAMESS did with
them. test_verified_inputs.py fails when this code stops producing those exact files.
"""

import os

from gamess_input_generator_pro.constants import (
    CCTYP,
    DFTTYP,
    ESP_FIELDS,
    GBASIS,
    SOLVENTS,
)
from gamess_input_generator_pro.group_builder import (
    apply_fields,
    build_input,
    cartesian_cards,
    format_groups,
    length_factor,
    needs_spherical,
    normalize_for_builder,
    parse_groups,
    zmatrix_cards,
)

HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "verified_inputs")
PUNCH = os.path.join(INPUTS, "punch")

WATER = [
    ("O", 8.0, 0.0, 0.0, 0.0),
    ("H", 1.0, 0.9572, 0.0, 0.0),
    ("H", 1.0, -0.2399, 0.9266, 0.0),
]
O2 = [("O", 8.0, 0.0, 0.0, 0.0), ("O", 8.0, 0.0, 0.0, 1.21)]
OH = [("O", 8.0, 0.0, 0.0, 0.0), ("H", 1.0, 0.0, 0.0, 0.97)]
NH3_PLANAR = [
    ("N", 7.0, 0.0, 0.0, 0.0),
    ("H", 1.0, 1.0, 0.0, 0.0),
    ("H", 1.0, -0.5, 0.866, 0.0),
    ("H", 1.0, -0.5, -0.866, 0.0),
]
H2O2_ZMAT = [
    {"symbol": "O", "refs": [], "values": []},
    {"symbol": "O", "refs": [0], "values": [1.45]},
    {"symbol": "H", "refs": [0, 1], "values": [0.97, 100.0]},
    {"symbol": "H", "refs": [1, 0, 2], "values": [0.97, 100.0, 115.0]},
]
GHOST_WATER = WATER + [("H", -1.0, 0.0, 0.0, 3.0)]
BQ_WATER = WATER + [("BQ", 0.0, 0.0, 0.0, 3.0)]

HF = {("CONTRL", "SCFTYP"): "RHF"}
B631GD = {
    ("BASIS", "GBASIS"): "N31",
    ("BASIS", "NGAUSS"): "6",
    ("BASIS", "NDFUNC"): "1",
}
STO3G = {("BASIS", "GBASIS"): "STO", ("BASIS", "NGAUSS"): "3"}
ENERGY = {("CONTRL", "RUNTYP"): "ENERGY"}


def _job(fields, atoms=WATER, charge=0, mult=1, cores=8, memddi=0, **more):
    return dict(
        fields=fields, atoms=atoms, charge=charge, mult=mult, cores=cores, memddi=memddi, **more
    )


def _fields(*parts, **_):
    merged = {}
    for part in parts:
        merged.update(part)
    return merged


B3LYP = {("CONTRL", "DFTTYP"): "B3LYP"}

JOBS = {
    "rhf_energy": _job(_fields(HF, ENERGY, B631GD)),
    "uhf_triplet": _job(
        _fields({("CONTRL", "SCFTYP"): "UHF"}, ENERGY, B631GD), O2, mult=3
    ),
    "rohf_triplet": _job(
        _fields({("CONTRL", "SCFTYP"): "ROHF"}, ENERGY, B631GD), O2, mult=3
    ),
    "b3lyp_opt": _job(
        _fields(HF, B3LYP, B631GD, {("CONTRL", "RUNTYP"): "OPTIMIZE", ("STATPT", "NSTEP"): "100"})
    ),
    "gradient": _job(_fields(HF, B631GD, {("CONTRL", "RUNTYP"): "GRADIENT"})),
    "hessian": _job(_fields(HF, B631GD, {("CONTRL", "RUNTYP"): "HESSIAN"})),
    "sadpoint": _job(
        _fields(
            HF,
            {("BASIS", "GBASIS"): "N21", ("BASIS", "NGAUSS"): "3"},
            {("CONTRL", "RUNTYP"): "SADPOINT", ("STATPT", "NSTEP"): "50"},
        ),
        NH3_PLANAR,
    ),
    "mp2": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "MPLEVL"): "2"})),
    "ccsd_t": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "CCTYP"): "CCSD(T)"}), memddi=50),
    "tddft": _job(
        _fields(
            HF, B3LYP, ENERGY, B631GD, {("CONTRL", "TDDFT"): "EXCITE", ("TDDFT", "NSTATE"): "3"}
        )
    ),
    "nmr": _job(_fields(HF, B631GD, {("CONTRL", "RUNTYP"): "NMR"}), cores=1),
    "pcm": _job(_fields(HF, ENERGY, B631GD, {("PCM", "SOLVNT"): "WATER"})),
    "smd": _job(_fields(HF, B3LYP, ENERGY, B631GD, {("PCM", "SOLVNT"): "WATER", ("PCM", "SMD"): ".TRUE."})),
    "d3": _job(_fields(HF, B3LYP, ENERGY, B631GD, {("DFT", "IDCVER"): "3"})),
    "d3bj": _job(_fields(HF, B3LYP, ENERGY, B631GD, {("DFT", "IDCVER"): "4"})),
    "basis_sto": _job(_fields(HF, ENERGY, STO3G)),
    "basis_n311": _job(
        _fields(
            HF,
            ENERGY,
            {
                ("BASIS", "GBASIS"): "N311",
                ("BASIS", "NGAUSS"): "6",
                ("BASIS", "NDFUNC"): "2",
                ("BASIS", "NFFUNC"): "1",
                ("BASIS", "NPFUNC"): "1",
                ("BASIS", "DIFFSP"): ".TRUE.",
                ("BASIS", "DIFFS"): ".TRUE.",
            },
        )
    ),
    "basis_pcseg": _job(_fields(HF, ENERGY, {("BASIS", "GBASIS"): "PCseg-1"})),
    "basis_acc": _job(_fields(HF, ENERGY, {("BASIS", "GBASIS"): "ACCD"})),
    "zmatrix": _job(_fields(HF, ENERGY, B631GD), zmat=H2O2_ZMAT),
    "zmatrix_opt": _job(
        _fields(HF, B631GD, {("CONTRL", "RUNTYP"): "OPTIMIZE", ("STATPT", "NSTEP"): "50"}),
        zmat=H2O2_ZMAT,
    ),
    "zmatrix_variables": _job(_fields(HF, ENERGY, B631GD), zmat=H2O2_ZMAT, variables=True),
    "ghost": _job(_fields(HF, ENERGY, B631GD), GHOST_WATER),
    "ghost_plain": _job(_fields(HF, ENERGY, B631GD), BQ_WATER),
    "units_bohr": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "UNITS"): "BOHR"})),
    "zmatrix_bohr": _job(
        _fields(HF, ENERGY, B631GD, {("CONTRL", "UNITS"): "BOHR"}), zmat=H2O2_ZMAT
    ),
    "esp": _job(_fields(HF, ENERGY, B631GD, ESP_FIELDS)),
    "print_orbitals": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "NPRINT"): "7"})),
    "cation": _job(
        _fields({("CONTRL", "SCFTYP"): "ROHF"}, ENERGY, B631GD), charge=1, mult=2
    ),
    "anion": _job(_fields(HF, ENERGY, B631GD), OH, charge=-1),
    "job_options": _job(
        _fields(
            HF,
            STO3G,
            {
                ("CONTRL", "RUNTYP"): "OPTIMIZE",
                ("STATPT", "OPTTOL"): "0.0001",
                ("STATPT", "NSTEP"): "50",
                ("STATPT", "HESS"): "CALC",
                ("STATPT", "HSSEND"): ".TRUE.",
                ("SCF", "DIRSCF"): ".TRUE.",
                ("GUESS", "GUESS"): "HCORE",
            },
        )
    ),
    "hess_seminum": _job(
        _fields(
            HF,
            STO3G,
            {
                ("CONTRL", "RUNTYP"): "HESSIAN",
                ("FORCE", "METHOD"): "SEMINUM",
                ("FORCE", "VIBANL"): ".TRUE.",
            },
        )
    ),
    "hess_fullnum": _job(
        _fields(HF, STO3G, {("CONTRL", "RUNTYP"): "HESSIAN", ("FORCE", "METHOD"): "FULLNUM"})
    ),
    "hess_guess": _job(
        _fields(HF, STO3G, {("CONTRL", "RUNTYP"): "OPTIMIZE", ("STATPT", "HESS"): "GUESS"})
    ),
    "hess_analytic": _job(
        _fields(HF, STO3G, {("CONTRL", "RUNTYP"): "HESSIAN", ("FORCE", "METHOD"): "ANALYTIC"})
    ),
    "guess_huckel": _job(_fields(HF, ENERGY, STO3G, {("GUESS", "GUESS"): "HUCKEL"})),
    "raman": _job(
        _fields(HF, B631GD, {("CONTRL", "RUNTYP"): "RAMAN"}), extra_file="raman_extra.txt"
    ),
    "hess_read": _job(
        _fields(
            HF, B631GD, {("CONTRL", "RUNTYP"): "OPTIMIZE", ("STATPT", "HESS"): "READ"}
        ),
        extra_file="hess_extra.txt",
    ),
    "moread": _job(
        _fields(HF, ENERGY, B631GD, {("GUESS", "GUESS"): "MOREAD", ("GUESS", "NORB"): "19"}),
        extra_file="vec_extra.txt",
    ),
}

# What GAMESS must refuse. Each one is what check_input warns about.
REFUSED = {
    "refuse_rhf_triplet": _job(_fields(HF, ENERGY, B631GD), O2, mult=3),
    "refuse_cc_no_memddi": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "CCTYP"): "CCSD(T)"})),
    "refuse_nmr_dft": _job(_fields(HF, B3LYP, B631GD, {("CONTRL", "RUNTYP"): "NMR"}), cores=1),
    "refuse_nmr_uhf": _job(_fields({("CONTRL", "SCFTYP"): "UHF"}, STO3G, {("CONTRL", "RUNTYP"): "NMR"}), O2, mult=3, cores=1),
    "refuse_pcseg_cartesian": _job(_fields(HF, ENERGY, {("BASIS", "GBASIS"): "PCseg-1"}), spherical=False),
    "refuse_cc_with_dft": _job(_fields(HF, B3LYP, ENERGY, B631GD, {("CONTRL", "CCTYP"): "CCSD"}), memddi=50),
    "refuse_sadpoint_no_hess": _job(_fields(HF, STO3G, {("CONTRL", "RUNTYP"): "SADPOINT", ("STATPT", "HESS"): "READ"}), NH3_PLANAR),
    "refuse_raman_no_hess": _job(_fields(HF, STO3G, {("CONTRL", "RUNTYP"): "RAMAN"})),
    "refuse_mp2_with_dft": _job(_fields(HF, B3LYP, ENERGY, B631GD, {("CONTRL", "MPLEVL"): "2"})),
    "refuse_mp2_with_cc": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "MPLEVL"): "2", ("CONTRL", "CCTYP"): "CCSD"}), memddi=50),
    "refuse_nmr_dirscf": _job(_fields(HF, B631GD, {("CONTRL", "RUNTYP"): "NMR", ("SCF", "DIRSCF"): ".TRUE."}), cores=1),
    "refuse_nmr_parallel": _job(_fields(HF, B631GD, {("CONTRL", "RUNTYP"): "NMR"}), cores=4),
    "refuse_lccd_parallel": _job(_fields(HF, ENERGY, B631GD, {("CONTRL", "CCTYP"): "LCCD"}), memddi=50),
    "refuse_bad_parity": _job(_fields({("CONTRL", "SCFTYP"): "ROHF"}, ENERGY, STO3G), mult=2),
}


def sweep_jobs():
    """One water job for every choice the builder offers from a long list."""
    jobs = {}
    for dfttyp in DFTTYP:
        jobs[f"sweep_dft_{dfttyp}"] = _job(
            _fields(HF, ENERGY, STO3G, {("CONTRL", "DFTTYP"): dfttyp})
        )
    for gbasis in GBASIS:
        basis = {("BASIS", "GBASIS"): gbasis}
        if gbasis in ("STO", "N21", "N31", "N311"):
            basis[("BASIS", "NGAUSS")] = "3" if gbasis in ("STO", "N21") else "6"
        jobs[f"sweep_basis_{gbasis}"] = _job(_fields(HF, ENERGY, basis))
    for cctyp in CCTYP:
        parallel = cctyp in ("CCSD", "CCSD(T)")
        jobs[f"sweep_cc_{cctyp}"] = _job(
            _fields(HF, ENERGY, B631GD, {("CONTRL", "CCTYP"): cctyp}),
            memddi=50 if parallel else 0,
            cores=8 if parallel else 1,
        )
    for solvent in SOLVENTS:
        jobs[f"sweep_pcm_{solvent}"] = _job(
            _fields(HF, ENERGY, STO3G, {("PCM", "SOLVNT"): solvent})
        )
    return jobs


def groups_text(job):
    """The groups the builder writes for these choices."""
    groups = apply_fields([], job["fields"])
    if job.get("spherical", True):
        groups = normalize_for_builder(groups)
    return format_groups(groups) + "\n"


def render(job, title):
    """The complete input file for a job, as the dialog would write it."""
    text = groups_text(job)
    length = length_factor(parse_groups(text))
    if "zmat" in job:
        cards = zmatrix_cards(job["zmat"], job.get("variables", False), length)
        coord = "ZMT"
    else:
        cards = cartesian_cards(job["atoms"], length)
        coord = "UNIQUE"
    extra = ""
    if "extra_file" in job:
        with open(os.path.join(PUNCH, job["extra_file"]), encoding="utf-8") as handle:
            extra = handle.read()
    return build_input(
        title,
        text,
        cards,
        job["charge"],
        job["mult"],
        100,
        job["memddi"],
        coord,
        extra,
    )


def file_name(name):
    """A job name usable as a GAMESS file name."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


__all__ = ["JOBS", "REFUSED", "needs_spherical", "render", "sweep_jobs", "file_name"]
