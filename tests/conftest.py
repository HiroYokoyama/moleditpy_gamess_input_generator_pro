"""Keeps the package importable, Qt headless, and temporary files in one place."""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SESSION_TMP = tempfile.mkdtemp(prefix="moleditpy_gamess_input_pro_tests_")
tempfile.tempdir = _SESSION_TMP


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)
