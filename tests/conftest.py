"""
tests/conftest.py

Prefer the real PySide6 over the per-module stubs when it is installed.

Several test modules call a local `_install_stubs()` that injects fake PySide6
modules into sys.modules so pure-logic paths can be tested without a GUI
toolkit.  Each of those helpers begins with:

    if "PySide6" in sys.modules:
        return

so importing the genuine PySide6 *here* -- conftest is loaded before any test
module -- makes them all no-ops, and the suite exercises real Qt widgets
instead of stubs.  That is what lets the GUI construction paths in
main_dialog.py, highlighter.py and mixins.py be covered at all.

When PySide6 is not installed this module does nothing and the stubs behave
exactly as before, so the suite still runs on a bare `pip install pytest`.
"""

import os as _os
import shutil as _shutil
import tempfile as _tempfile

# Tests mkdtemp() without removing it, so every run left directories in the
# system temp directory. Everything a run creates -- in this process and in the
# processes it starts -- goes under one directory removed at session end.
if _os.path.abspath(_tempfile.gettempdir()) == _os.path.abspath(_os.getcwd()):
    _tempfile.tempdir = _os.path.abspath(
        _os.environ.get("RUNNER_TEMP") or _os.path.expanduser("~/.cache/moleditpy_gaussian_input_generator_pro_tests")
    )
    _os.makedirs(_tempfile.tempdir, exist_ok=True)
_SESSION_TMP = _tempfile.mkdtemp(prefix="moleditpy_gaussian_input_generator_pro_tests_")
_tempfile.tempdir = _SESSION_TMP
for _name in ("TMP", "TEMP", "TMPDIR"):
    _os.environ[_name] = _SESSION_TMP

import os

# Must be set before QApplication is constructed; makes Qt run headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PySide6-less environments
    QApplication = None


if QApplication is not None:
    # A single QApplication must outlive every test in the session; Qt aborts
    # if widgets are created without one.
    _app = QApplication.instance() or QApplication([])

    # Some sibling test modules (test_keyword_builder.py, test_metadata.py,
    # ...) unconditionally overwrite sys.modules["PySide6*"] with permissive
    # stub modules once they are collected, with no regard for import order.
    # Stash the genuine module objects under alternate keys *now*, while they
    # are still guaranteed real, so any test needing real Qt later in the
    # session (e.g. test_main_dialog_extended.py, which builds a real
    # QDialog) can recover them. This only stores an extra dict entry
    # pointing at the same already-initialized module objects -- it never
    # re-imports/re-registers the PySide6 sip bindings, which would crash.
    import sys as _sys

    for _name in ("PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"):
        _mod = _sys.modules.get(_name)
        if _mod is not None:
            _sys.modules[_name + "__real"] = _mod

# Same stash for rdkit -- several sibling test modules unconditionally
# replace sys.modules["rdkit"] etc. with unittest.mock.MagicMock() instances.
try:
    import rdkit as _rdkit
    import rdkit.Chem as _rdkit_chem
    import rdkit.Chem.AllChem as _rdkit_allchem
    import rdkit.Chem.rdMolTransforms as _rdkit_rdmt
    import sys as _sys

    for _name, _mod in (
        ("rdkit", _rdkit),
        ("rdkit.Chem", _rdkit_chem),
        ("rdkit.Chem.AllChem", _rdkit_allchem),
        ("rdkit.Chem.rdMolTransforms", _rdkit_rdmt),
    ):
        _sys.modules[_name + "__real"] = _mod
except ImportError:  # pragma: no cover - rdkit-less environments
    pass


def pytest_sessionfinish(session, exitstatus):
    _shutil.rmtree(_SESSION_TMP, ignore_errors=True)
