"""The code still writes the files GAMESS accepted, and every claim names one."""

import json
import os
import re
import unittest

import claimed_features as C
import verified_jobs as V

from gamess_input_generator_pro.constants import (
    BUILDER_TABS,
    CCTYP,
    DFTTYP,
    ESP_FIELDS,
    GBASIS,
    SOLVENTS,
)
from gamess_input_generator_pro.group_builder import (
    check_input,
    parse_groups,
    split_groups,
)
from gamess_input_generator_pro.input_loading import parse_input

with open(os.path.join(V.INPUTS, "RESULTS.json"), encoding="utf-8") as handle:
    RESULTS = json.load(handle)


def _read(name):
    with open(os.path.join(V.INPUTS, name + ".inp"), encoding="utf-8") as handle:
        return handle.read()


class TestGoldenFiles(unittest.TestCase):
    def test_every_job_still_renders_the_same_file(self):
        for name, job in V.JOBS.items():
            with self.subTest(job=name):
                self.assertEqual(V.render(job, f"MoleditPy test: {name}"), _read(name))

    def test_every_file_ran_to_normal_termination(self):
        for name in V.JOBS:
            with self.subTest(job=name):
                self.assertEqual(RESULTS["jobs"][name]["terminated"], "normally")

    def test_the_program_version_is_recorded(self):
        self.assertRegex(RESULTS["program"], r"2024 \(R2")

    def test_every_file_is_read_back(self):
        for name in V.JOBS:
            with self.subTest(job=name):
                settings, rows, notes = parse_input(_read(name), name + ".inp")
                self.assertEqual(notes, [])
                self.assertGreaterEqual(len(rows), 2)
                self.assertEqual(settings["charge"], V.JOBS[name]["charge"])
                self.assertEqual(settings["mult"], V.JOBS[name]["mult"])

    def test_no_card_passes_column_80(self):
        for name in V.JOBS:
            head = _read(name).split(" $DATA")[0]
            for line in head.splitlines():
                self.assertLessEqual(len(line), 80, name)
                self.assertEqual(line[0], " ", name)


class TestScience(unittest.TestCase):
    """Results that could only come out right if the cards meant what they should."""

    @staticmethod
    def energy(name):
        return RESULTS["jobs"][name]["energy"]

    def test_bohr_gives_the_same_molecule(self):
        self.assertAlmostEqual(
            self.energy("units_bohr"), self.energy("rhf_energy"), places=6
        )
        self.assertAlmostEqual(
            self.energy("zmatrix_bohr"), self.energy("zmatrix"), places=6
        )

    def test_variables_give_the_same_molecule(self):
        self.assertEqual(self.energy("zmatrix_variables"), self.energy("zmatrix"))

    def test_plain_dummy_changes_nothing(self):
        self.assertEqual(self.energy("ghost_plain"), self.energy("rhf_energy"))

    def test_ghost_basis_lowers_the_energy_a_little(self):
        change = self.energy("ghost") - self.energy("rhf_energy")
        self.assertLess(change, 0.0)
        self.assertGreater(change, -0.01)

    def test_water_matches_the_literature(self):
        # RHF/6-31G(d) of water near its equilibrium geometry is -76.01 hartree.
        self.assertAlmostEqual(self.energy("rhf_energy"), -76.0105, places=3)

    def test_correlation_lowers_the_energy(self):
        self.assertLess(self.energy("mp2"), self.energy("rhf_energy"))
        self.assertLess(self.energy("ccsd_t"), self.energy("rhf_energy"))

    def test_solvent_lowers_the_energy(self):
        self.assertLess(self.energy("pcm"), self.energy("rhf_energy"))

    def test_triplet_oxygen_uhf_is_below_rohf(self):
        self.assertLess(self.energy("uhf_triplet"), self.energy("rohf_triplet"))

    def test_dispersion_versions_differ(self):
        self.assertNotEqual(self.energy("d3"), self.energy("d3bj"))

    def test_raman_activities_were_computed(self):
        self.assertTrue(RESULTS["jobs"]["raman"]["raman_activity"])

    def test_moread_converges_at_once(self):
        self.assertLessEqual(RESULTS["jobs"]["moread"]["iterations"], 2)
        self.assertAlmostEqual(
            self.energy("moread"), self.energy("rhf_energy"), places=6
        )


class TestClaims(unittest.TestCase):
    def test_every_claim_has_a_finished_job(self):
        for claim, name in C.CLAIMS.items():
            with self.subTest(claim=claim):
                self.assertIn(name, V.JOBS)
                self.assertEqual(RESULTS["jobs"][name]["terminated"], "normally")

    def test_every_job_backs_a_claim(self):
        self.assertEqual(set(V.JOBS) - set(C.CLAIMS.values()), set())

    def test_every_long_list_choice_really_ran(self):
        expected = {f"sweep_dft_{name}" for name in DFTTYP}
        expected |= {f"sweep_basis_{name}" for name in GBASIS}
        expected |= {f"sweep_cc_{name}" for name in CCTYP}
        expected |= {f"sweep_pcm_{name}" for name in SOLVENTS}
        self.assertEqual(set(RESULTS["sweep"]), expected)
        for name, outcome in RESULTS["sweep"].items():
            with self.subTest(job=name):
                self.assertEqual(outcome, "normally")

    def test_every_builder_keyword_is_used_by_a_finished_job(self):
        used = set()
        for job in V.JOBS.values():
            used.update(job["fields"])
        for fields in BUILDER_TABS.values():
            for _, group, key, _, _ in fields:
                with self.subTest(keyword=f"${group} {key}"):
                    self.assertIn((group, key), used)
        self.assertTrue(set(ESP_FIELDS) <= used)

    def test_every_word_choice_is_used_by_a_finished_job(self):
        used = set()
        for job in V.JOBS.values():
            used.update(job["fields"].items())
        lists = (DFTTYP, GBASIS, CCTYP, SOLVENTS)
        for fields in BUILDER_TABS.values():
            for _, group, key, kind, choices in fields:
                if kind != "combo" or any(choices is long for long in lists):
                    continue
                for choice in choices:
                    if re.fullmatch(r"[\d.]+", choice):
                        continue
                    with self.subTest(keyword=f"${group} {key}={choice}"):
                        self.assertIn(((group, key), choice), used)

    def test_no_control_for_what_gamess_cannot_do(self):
        keys = {key for fields in BUILDER_TABS.values() for _, _, key, _, _ in fields}
        for absent in ("NBO", "SCAN", "CONSTR", "IFREEZ"):
            self.assertNotIn(absent, keys)


class TestRefusals(unittest.TestCase):
    def test_every_warning_is_something_gamess_refused(self):
        self.assertEqual(set(C.REFUSALS), set(V.REFUSED))
        for name, (_, printed) in C.REFUSALS.items():
            with self.subTest(job=name):
                self.assertEqual(RESULTS["refused"][name]["terminated"], "abnormally")
                self.assertIn(printed, RESULTS["refused"][name]["message"])

    def test_check_input_warns_about_each_of_them(self):
        for name, (warning, _) in C.REFUSALS.items():
            job = V.REFUSED[name]
            electrons = 10 if job["atoms"] is V.WATER else None
            with self.subTest(job=name):
                notes = check_input(
                    parse_groups(V.groups_text(job)),
                    job["mult"],
                    electrons,
                    job["memddi"],
                )
                self.assertIn(warning, " ".join(notes))

    def test_no_warning_on_any_accepted_job(self):
        for name, job in V.JOBS.items():
            if name == "nmr":  # the one-core reminder always shows, and it is honest
                continue
            blocks = split_groups(_read(name))
            extra = "\n".join(
                raw for block, _, raw in blocks if block in ("HESS", "DIPDR", "VEC")
            )
            with self.subTest(job=name):
                self.assertEqual(
                    check_input(
                        parse_groups(V.groups_text(job)),
                        job["mult"],
                        None,
                        job["memddi"],
                        extra,
                    ),
                    [],
                )


class TestPrivacy(unittest.TestCase):
    FORBIDDEN = re.compile(r"/home/|/Users/|[A-Za-z]:\\|DESKTOP-|@[\w-]+\.\w+")

    def test_committed_files_name_no_machine_or_person(self):
        for name in os.listdir(V.INPUTS) + [
            os.path.join("punch", p) for p in os.listdir(V.PUNCH)
        ]:
            path = os.path.join(V.INPUTS, name)
            if os.path.isdir(path):
                continue
            with open(path, encoding="utf-8") as handle:
                self.assertIsNone(self.FORBIDDEN.search(handle.read()), name)


if __name__ == "__main__":
    unittest.main()
