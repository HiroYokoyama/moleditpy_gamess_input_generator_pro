"""GAMESS input cards as pure text: no Qt and no RDKit, so all of it runs under test."""

import re

BOHR_ANGSTROM = 0.529177210903

ELEMENTS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
    "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po "
    "At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg "
    "Cn Nh Fl Mc Lv Ts Og"
).split()

# GAMESS keeps only the first 80 columns; group text must start at column 2 or later.
CARD_WIDTH = 79
TITLE_WIDTH = 80

_GROUP = re.compile(
    r"^[ \t]*\$(\w+)\b(.*?)\$END\b", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
_OPTION = re.compile(r"([A-Za-z]\w*(?:\([\d,]+\))?)\s*=\s*(\S+)")
_MODERN_BASIS = re.compile(
    r"^(A?CC[DTQ56](C|WC)?|A?PCSEG-\d|SPK.*|KTZV.*)$", re.IGNORECASE
)


def strip_comments(text):
    """Drop what GAMESS treats as a comment: a ! to the end of its card."""
    return "\n".join(line.split("!", 1)[0] for line in text.splitlines())


def _parse_options(body):
    """The KEY=VALUE pairs of a group body; ValueError when anything else is there."""
    body = strip_comments(body)
    options = [(m[1].upper(), m[2]) for m in _OPTION.finditer(body)]
    if _OPTION.sub(" ", body).strip():
        raise ValueError(f"Not KEY=VALUE input: {_OPTION.sub(' ', body).split()[0]}")
    return options


def parse_groups(text):
    """Read option groups as [(NAME, [(KEY, VALUE), ...]), ...]."""
    groups, position = [], 0
    source = strip_comments(text)
    for match in _GROUP.finditer(source):
        if source[position : match.start()].strip():
            raise ValueError(
                f"Text outside a group: {source[position : match.start()].split()[0]}"
            )
        name = match[1].upper()
        try:
            groups.append((name, _parse_options(match[2])))
        except ValueError as exc:
            raise ValueError(
                f"${name} holds free-form data; it belongs in Extra Groups. ({exc})"
            ) from None
        position = match.end()
    rest = source[position:].strip()
    if rest:
        raise ValueError(f"Group not closed with $END: {rest.split()[0]}")
    return groups


def split_groups(text):
    """Every group as (NAME, raw body, raw text), in file order."""
    return [(m[1].upper(), m[2], m[0]) for m in _GROUP.finditer(text)]


def format_group(name, options, width=CARD_WIDTH):
    """Cards of one group: column 1 blank, wrapped so nothing passes column 80."""
    lines, line = [], f" ${name}"
    for token in [f"{key}={value}" for key, value in options] + ["$END"]:
        if len(line) + 1 + len(token) > width:
            lines.append(line)
            line = "  " + token
        else:
            line += " " + token
    lines.append(line)
    return lines


def format_groups(groups):
    """Cards of every group, dropping a group left with no options."""
    return "\n".join(
        "\n".join(format_group(name, options)) for name, options in groups if options
    )


def get_option(groups, name, key, default=None):
    """The last value given for $NAME KEY, as GAMESS would read it."""
    found = default
    for group, options in groups:
        if group == name:
            for option, value in options:
                if option == key:
                    found = value
    return found


def set_option(groups, name, key, value):
    """A copy of groups with $NAME KEY set, or removed when value is None or ''."""
    result, done = [], value in (None, "")
    for group, options in groups:
        options = list(options)
        if group == name:
            if not done and any(option == key for option, _ in options):
                options = [
                    (option, value if option == key else current)
                    for option, current in options
                ]
                done = True
            else:
                options = [item for item in options if item[0] != key]
        result.append((group, options))
    if not done:
        for index, (group, options) in enumerate(result):
            if group == name:
                result[index] = (group, options + [(key, value)])
                break
        else:
            result.append((name, [(key, value)]))
    return result


def needs_spherical(gbasis):
    """Correlation-consistent, PCseg, SPK and KTZV sets stop without ISPHER=1."""
    return bool(gbasis and _MODERN_BASIS.match(gbasis))


def finalize_groups(groups, charge, mult, mwords, memddi, coord):
    """Charge, multiplicity, coordinates and memory set; $CONTRL and $SYSTEM first."""
    groups = set_option(groups, "CONTRL", "ICHARG", str(charge))
    groups = set_option(groups, "CONTRL", "MULT", str(mult))
    groups = set_option(groups, "CONTRL", "COORD", coord)
    groups = set_option(groups, "SYSTEM", "MWORDS", str(mwords))
    groups = set_option(groups, "SYSTEM", "MEMDDI", str(memddi) if memddi else None)
    rank = {"CONTRL": 0, "SYSTEM": 1}
    return sorted(groups, key=lambda group: rank.get(group[0], 2))


def length_factor(groups):
    """Input length per Angstrom, from UNITS. Angles are always degrees."""
    units = str(get_option(groups, "CONTRL", "UNITS", "ANGS")).upper()
    return 1.0 / BOHR_ANGSTROM if units.startswith("BOHR") else 1.0


def cartesian_cards(atoms, length=1.0):
    """`label ZNUC x y z` cards; a negative ZNUC is a ghost with that atom's basis."""
    return [
        f"{label:<4} {znuc:>6.1f} {x * length:>14.8f} "
        f"{y * length:>14.8f} {z * length:>14.8f}"
        for label, znuc, x, y, z in atoms
    ]


def zmatrix_cards(rows, variables=False, length=1.0):
    """COORD=ZMT cards; with variables, a blank card and then `NAME VALUE` cards."""
    lines, defined = [], []
    for index, row in enumerate(rows):
        fields = [f"{row['symbol']:<4}"]
        scaled = zip("BAD", row["refs"], row["values"], (length, 1.0, 1.0))
        for prefix, ref, value, factor in scaled:
            value *= factor
            if variables:
                name = f"{prefix}{index + 1}"
                defined.append(f"{name:<6} {value:.8f}")
                fields.append(f"{ref + 1:>3} {name}")
            else:
                fields.append(f"{ref + 1:>3} {value:.8f}")
        lines.append("  ".join(fields).rstrip())
    if defined:
        lines.append("")
        lines.extend(defined)
    return lines


def data_group(title, cards):
    """The $DATA group: title, C1 and coordinates. C1 takes no blank card after it."""
    title = " ".join(title.split())[:TITLE_WIDTH] or "GAMESS Job"
    return [" $DATA", title, "C1", *cards, " $END"]


def build_input(title, groups, cards, charge, mult, mwords, memddi, coord, extra=""):
    """The complete input file. groups is the text of the option groups."""
    final = finalize_groups(parse_groups(groups), charge, mult, mwords, memddi, coord)
    parts = [format_groups(final), "\n".join(data_group(title, cards))]
    if extra.strip():
        parts.append(extra.strip("\n"))
    return "\n".join(parts) + "\n"


def check_input(groups, mult, electrons=None, memddi=0, extra=""):
    """Why GAMESS would refuse this job, or what it would need; [] when nothing."""
    notes = []
    scftyp = str(get_option(groups, "CONTRL", "SCFTYP", "RHF")).upper()
    runtyp = str(get_option(groups, "CONTRL", "RUNTYP", "ENERGY")).upper()
    dfttyp = str(get_option(groups, "CONTRL", "DFTTYP", "NONE")).upper()
    cctyp = str(get_option(groups, "CONTRL", "CCTYP", "NONE")).upper()
    mplevl = str(get_option(groups, "CONTRL", "MPLEVL", "0"))
    dirscf = str(get_option(groups, "SCF", "DIRSCF", "")).upper()
    gbasis = get_option(groups, "BASIS", "GBASIS")
    ispher = str(get_option(groups, "CONTRL", "ISPHER", "-1"))
    extra_names = {name for name, _, _ in split_groups(extra)}

    if electrons is not None and (electrons < mult - 1 or (electrons - mult + 1) % 2):
        notes.append(f"{electrons} electrons cannot have multiplicity {mult}.")
    if scftyp == "RHF" and mult != 1:
        notes.append("SCFTYP=RHF needs MULT=1. Choose ROHF or UHF for an open shell.")
    if needs_spherical(gbasis) and ispher != "1":
        notes.append(f"GBASIS={gbasis} needs ISPHER=1 in $CONTRL.")
    if cctyp in ("CCSD", "CCSD(T)") and not memddi:
        notes.append(f"CCTYP={cctyp} needs MEMDDI above zero.")
    elif cctyp != "NONE" and cctyp not in ("CCSD", "CCSD(T)"):
        notes.append(f"CCTYP={cctyp} runs on one core only, with MEMDDI=0.")
    methods = (dfttyp != "NONE", mplevl != "0", cctyp != "NONE")
    if sum(methods) > 1:
        notes.append("Choose at most one of DFTTYP, MPLEVL and CCTYP.")
    if runtyp == "NMR" and (dfttyp != "NONE" or scftyp != "RHF"):
        notes.append("RUNTYP=NMR works only with RHF: no DFT, no open shell.")
    if runtyp == "NMR" and dirscf in (".TRUE.", ".T."):
        notes.append("RUNTYP=NMR does not work with DIRSCF.")
    if runtyp == "NMR":
        notes.append("RUNTYP=NMR runs serially: submit it on one core.")
    if runtyp == "RAMAN" and not {"HESS", "DIPDR"} <= extra_names:
        notes.append(
            "RUNTYP=RAMAN needs $HESS and $DIPDR from a Hessian job's punch file "
            "in Extra Groups."
        )
    hess = str(get_option(groups, "STATPT", "HESS", "READ")).upper()
    if runtyp == "SADPOINT" and hess == "READ" and "HESS" not in extra_names:
        notes.append(
            "RUNTYP=SADPOINT reads a $HESS group by default. Add one to Extra "
            "Groups, or set HESS=CALC in $STATPT."
        )
    return notes


def apply_fields(groups, values):
    """Apply {(GROUP, KEY): value} to groups, leaving every other option alone."""
    for (name, key), value in values.items():
        groups = set_option(groups, name, key, value)
    return [(name, options) for name, options in groups if options]


def normalize_for_builder(groups):
    """The settings GAMESS requires for what was picked, and no more."""
    gbasis = get_option(groups, "BASIS", "GBASIS")
    if needs_spherical(gbasis):
        groups = set_option(groups, "CONTRL", "ISPHER", "1")
    if str(get_option(groups, "CONTRL", "RUNTYP", "")).upper() == "SADPOINT":
        if get_option(groups, "STATPT", "HESS") is None:
            groups = set_option(groups, "STATPT", "HESS", "CALC")
    return groups
