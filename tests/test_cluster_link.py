"""The optional Job Manager handoff.

The whole point of this module is that the plugin behaves identically when Job
Manager is absent, so most of these tests are about *not* doing things.

cluster_link is loaded straight from its file rather than imported through the
package: gamess_input_generator_pro/__init__.py imports PySide6, and CI installs pytest only. The module
itself needs nothing beyond the standard library, which is precisely why the
handoff can be probed before any GUI exists.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gamess_input_generator_pro",
    "cluster_link.py",
)
_spec = importlib.util.spec_from_file_location("_cluster_link_under_test", _MODULE_PATH)
cluster_link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cluster_link)



class FakeJobManagerModule:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def submit_file(self, path, name=""):
        self.calls.append((path, name))
        return self.result


def make_main_window(plugins):
    main_window = MagicMock()
    main_window.plugin_manager.plugins = plugins
    return main_window


class TestFindJobManager(unittest.TestCase):
    def test_found_when_present(self):
        module = FakeJobManagerModule()
        found = cluster_link.find_job_manager(
            make_main_window([{"name": "Job Manager", "module": module}])
        )
        self.assertIs(found, module)

    def test_absent_from_an_empty_plugin_list(self):
        self.assertIsNone(cluster_link.find_job_manager(make_main_window([])))

    def test_other_plugins_are_not_mistaken_for_it(self):
        plugins = [
            {"name": "Cube File Viewer", "module": FakeJobManagerModule()},
            {"name": "Auto Rotator", "module": FakeJobManagerModule()},
        ]
        self.assertIsNone(cluster_link.find_job_manager(make_main_window(plugins)))

    def test_a_version_without_the_api_counts_as_absent(self):
        # Identified by capability, not just by name.
        plugins = [{"name": "Job Manager", "module": types.SimpleNamespace()}]
        self.assertIsNone(cluster_link.find_job_manager(make_main_window(plugins)))

    def test_a_none_module_is_skipped(self):
        plugins = [{"name": "Job Manager", "module": None}]
        self.assertIsNone(cluster_link.find_job_manager(make_main_window(plugins)))

    def test_a_non_callable_submit_file_counts_as_absent(self):
        module = types.SimpleNamespace(submit_file="not a function")
        plugins = [{"name": "Job Manager", "module": module}]
        self.assertIsNone(cluster_link.find_job_manager(make_main_window(plugins)))

    def test_a_host_without_a_plugin_manager(self):
        self.assertIsNone(cluster_link.find_job_manager(object()))

    def test_a_plugin_manager_without_a_plugin_list(self):
        main_window = MagicMock()
        main_window.plugin_manager.plugins = None
        self.assertIsNone(cluster_link.find_job_manager(main_window))

    def test_a_malformed_record_does_not_break_the_scan(self):
        module = FakeJobManagerModule()
        plugins = ["not a dict", {"name": "Job Manager", "module": module}]
        self.assertIs(cluster_link.find_job_manager(make_main_window(plugins)), module)

    def test_is_available_mirrors_the_lookup(self):
        self.assertFalse(cluster_link.is_available(make_main_window([])))
        self.assertTrue(
            cluster_link.is_available(
                make_main_window(
                    [{"name": "Job Manager", "module": FakeJobManagerModule()}]
                )
            )
        )


class TestSubmitToCluster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cluster_link_")
        self.path = os.path.join(self.tmp, "mol.gjf")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("! B3LYP\n")
        self.module = FakeJobManagerModule()
        self.main_window = make_main_window(
            [{"name": "Job Manager", "module": self.module}]
        )

    def test_forwards_the_path_and_name(self):
        self.assertTrue(
            cluster_link.submit_to_cluster(self.main_window, self.path, name="run1")
        )
        self.assertEqual(self.module.calls, [(self.path, "run1")])

    def test_returns_false_when_job_manager_is_absent(self):
        self.assertFalse(
            cluster_link.submit_to_cluster(make_main_window([]), self.path)
        )

    def test_returns_false_for_a_missing_file(self):
        missing = os.path.join(self.tmp, "nope.inp")
        self.assertFalse(cluster_link.submit_to_cluster(self.main_window, missing))
        self.assertEqual(self.module.calls, [])

    def test_returns_false_for_an_empty_path(self):
        self.assertFalse(cluster_link.submit_to_cluster(self.main_window, ""))

    def test_a_declining_job_manager_is_reported(self):
        self.module.result = False
        self.assertFalse(cluster_link.submit_to_cluster(self.main_window, self.path))

    def test_an_exception_in_job_manager_is_contained(self):
        def explode(path, name=""):
            raise RuntimeError("boom")

        self.module.submit_file = explode
        self.assertFalse(cluster_link.submit_to_cluster(self.main_window, self.path))


if __name__ == "__main__":
    unittest.main()
