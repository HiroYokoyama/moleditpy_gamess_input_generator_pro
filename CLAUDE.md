# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A MoleditPy plugin that writes and reads GAMESS (US) input files.
`gamess_input_generator_pro/` is the whole plugin; it ships as a zip of that directory.
It is at 0.2.0.

## Layout

- `group_builder.py`: option groups and coordinate cards as pure text, plus `check_input`.
  No Qt and no RDKit, so all of it runs under test.
- `input_loading.py`: `parse_input` and file reading. Qt and RDKit are imported lazily.
- `constants.py`: the builder's choices. A choice in a long list needs a sweep job.
- `keyword_builder.py`: `GamessGroupBuilderDialog`, generated from `BUILDER_TABS`.
- `main_dialog.py`: `GamessSetupDialogPro`.
- `__init__.py`: the plugin contract. It imports no Qt at module level.

## Features follow the program

Add a control only for what GAMESS 2024 R2 really does, and a warning only for what it
really refuses. Run the job first: `tests/verified_jobs.py` holds the jobs,
`tests/claimed_features.py` says what each one proves, `tests/verified_inputs` holds the
files and `RESULTS.json` what GAMESS did with them. A new claim needs all of these.

Facts that were tested, and cost time:

- Groups start at column 2, on their own card. A second group on the same card is lost.
- Angles in `$DATA` are degrees. `AUNITS` is not a keyword.
- `RUNTYP=NMR` is RHF only, no DFT, no `DIRSCF`, one core.
- Only `CCSD` and `CCSD(T)` run in parallel, and those need `MEMDDI`. Every other `CCTYP`
  needs one core and `MEMDDI=0`. Coupled cluster needs more virtual than occupied
  orbitals, so water in STO-3G stops.
- `SADPOINT` defaults to `HESS=READ`. Raman needs the last `$HESS` of the punch file; the
  first is the optimizer's approximation.
- Under `COORD=ZMT`, variables follow a blank card, as `NAME VALUE`.

## Testing

```bash
python -m pytest tests/test_group_builder.py tests/test_input_parsing.py tests/test_verified_inputs.py -q
python -m pytest tests/test_real_dialog.py -q
```

CI runs the headless suite in `tests.yml` and real windows in `qt-callbacks.yml`.
The package must import without Qt; `REQUIRE_REAL_QT=1` makes missing real-window
dependencies a failure in the Qt job.

## Privacy

Files in `tests/verified_inputs` are textbook molecules only. The test suite refuses a
path, host name or mail address in them. Never commit a GAMESS output: it records the
machine, or any GAMESS source.

## Version

`PLUGIN_VERSION` in `__init__.py` is the single source of truth. Tags, releases and the
registry entry wait for the user's word. `scripts/zenodo-config.json` has no deposition
yet. The user authorized publishing v0.1.1 without Zenodo on 2026-11-08.

## Copied maintenance scripts

See [scripts/COMMON_TOOLS.md](scripts/COMMON_TOOLS.md) for canonical ownership, pinned versions and update instructions. Common script unit tests stay in the canonical repository; retain this repository's own integration checks.
