"""Cards, groups and warnings, without Qt."""

import unittest

from gamess_input_generator_pro.group_builder import (
    BOHR_ANGSTROM,
    apply_fields,
    build_input,
    cartesian_cards,
    check_input,
    data_group,
    finalize_groups,
    format_group,
    format_groups,
    get_option,
    length_factor,
    needs_spherical,
    normalize_for_builder,
    parse_groups,
    set_option,
    split_groups,
    zmatrix_cards,
)


class TestParseGroups(unittest.TestCase):
    def test_reads_options_in_upper_case_keys(self):
        groups = parse_groups(" $contrl scftyp=RHF RUNTYP = ENERGY $end\n")
        self.assertEqual(
            groups, [("CONTRL", [("SCFTYP", "RHF"), ("RUNTYP", "ENERGY")])]
        )

    def test_group_may_span_cards(self):
        groups = parse_groups(
            " $CONTRL SCFTYP=RHF\n  RUNTYP=ENERGY $END\n $BASIS GBASIS=STO $END"
        )
        self.assertEqual(get_option(groups, "CONTRL", "RUNTYP"), "ENERGY")
        self.assertEqual(get_option(groups, "BASIS", "GBASIS"), "STO")

    def test_comments_are_ignored(self):
        groups = parse_groups("! a note\n $CONTRL SCFTYP=RHF ! RUNTYP=NMR\n $END\n")
        self.assertIsNone(get_option(groups, "CONTRL", "RUNTYP"))

    def test_unclosed_group_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "not closed"):
            parse_groups(" $CONTRL SCFTYP=RHF\n")

    def test_text_outside_a_group_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            parse_groups("hello\n $CONTRL SCFTYP=RHF $END\n")

    def test_free_form_group_belongs_in_extra(self):
        with self.assertRaisesRegex(ValueError, "Extra Groups"):
            parse_groups(" $HESS\n 1 1 1.0 2.0\n $END\n")

    def test_value_with_parentheses(self):
        groups = parse_groups(" $CONTRL CCTYP=CCSD(T) $END")
        self.assertEqual(get_option(groups, "CONTRL", "CCTYP"), "CCSD(T)")

    def test_split_groups_keeps_raw_text(self):
        blocks = split_groups(" $HESS\n 1 2\n $END\n $VEC\n 3\n $END\n")
        self.assertEqual([name for name, _, _ in blocks], ["HESS", "VEC"])
        self.assertIn(" 1 2", blocks[0][2])


class TestFormatGroup(unittest.TestCase):
    def test_column_one_is_blank(self):
        for line in format_group("CONTRL", [("SCFTYP", "RHF")]):
            self.assertEqual(line[0], " ")

    def test_long_group_wraps_inside_80_columns(self):
        options = [(f"KEYWORD{i}", "VALUE") for i in range(30)]
        lines = format_group("CONTRL", options)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(len(line), 80)
            self.assertEqual(line[0], " ")
        self.assertTrue(lines[-1].endswith("$END"))
        self.assertEqual(parse_groups("\n".join(lines))[0][1], options)

    def test_empty_group_is_dropped(self):
        self.assertEqual(format_groups([("PCM", [])]), "")


class TestSetOption(unittest.TestCase):
    def test_repeated_groups_cannot_override_the_new_setting(self):
        groups = parse_groups(
            " $CONTRL ICHARG=0 MULT=1 $END\n $CONTRL ICHARG=2 NPRINT=7 $END"
        )
        updated = set_option(groups, "CONTRL", "ICHARG", "1")
        self.assertEqual(get_option(updated, "CONTRL", "ICHARG"), "1")
        self.assertEqual(get_option(updated, "CONTRL", "NPRINT"), "7")
        self.assertEqual(get_option(groups, "CONTRL", "ICHARG"), "2")

    def test_adds_group_when_missing(self):
        groups = set_option([], "PCM", "SOLVNT", "WATER")
        self.assertEqual(groups, [("PCM", [("SOLVNT", "WATER")])])

    def test_replaces_in_place(self):
        groups = set_option([("CONTRL", [("A", "1"), ("B", "2")])], "CONTRL", "A", "9")
        self.assertEqual(groups, [("CONTRL", [("A", "9"), ("B", "2")])])

    def test_none_removes(self):
        groups = set_option([("CONTRL", [("A", "1"), ("B", "2")])], "CONTRL", "A", None)
        self.assertEqual(groups, [("CONTRL", [("B", "2")])])

    def test_does_not_change_its_argument(self):
        original = [("CONTRL", [("A", "1")])]
        set_option(original, "CONTRL", "A", "2")
        self.assertEqual(original, [("CONTRL", [("A", "1")])])


class TestFinalize(unittest.TestCase):
    def test_contrl_and_system_come_first(self):
        groups = finalize_groups(
            [("BASIS", [("GBASIS", "STO")])], 0, 1, 100, 0, "UNIQUE"
        )
        self.assertEqual([name for name, _ in groups], ["CONTRL", "SYSTEM", "BASIS"])

    def test_generated_values_replace_typed_ones(self):
        typed = [
            ("CONTRL", [("ICHARG", "5"), ("MULT", "7"), ("COORD", "HINT")]),
            ("SYSTEM", [("MWORDS", "1"), ("MEMDDI", "9")]),
        ]
        groups = finalize_groups(typed, -1, 2, 50, 0, "ZMT")
        self.assertEqual(get_option(groups, "CONTRL", "ICHARG"), "-1")
        self.assertEqual(get_option(groups, "CONTRL", "MULT"), "2")
        self.assertEqual(get_option(groups, "CONTRL", "COORD"), "ZMT")
        self.assertEqual(get_option(groups, "SYSTEM", "MWORDS"), "50")
        self.assertIsNone(get_option(groups, "SYSTEM", "MEMDDI"))

    def test_memddi_written_when_set(self):
        groups = finalize_groups([], 0, 1, 50, 25, "UNIQUE")
        self.assertEqual(get_option(groups, "SYSTEM", "MEMDDI"), "25")


class TestCards(unittest.TestCase):
    ATOMS = [("O", 8.0, 0.0, 0.0, 0.0), ("H", -1.0, 0.0, 0.0, 1.0)]

    def test_cartesian_has_label_znuc_xyz(self):
        fields = cartesian_cards(self.ATOMS)[0].split()
        self.assertEqual(fields[:2], ["O", "8.0"])
        self.assertEqual(len(fields), 5)

    def test_ghost_keeps_negative_znuc(self):
        self.assertEqual(cartesian_cards(self.ATOMS)[1].split()[1], "-1.0")

    def test_units_bohr_converts_coordinates(self):
        factor = length_factor([("CONTRL", [("UNITS", "BOHR")])])
        z = float(cartesian_cards(self.ATOMS, factor)[1].split()[4])
        self.assertAlmostEqual(z * BOHR_ANGSTROM, 1.0, places=6)

    def test_plain_zmatrix(self):
        rows = [
            {"symbol": "O", "refs": [], "values": []},
            {"symbol": "H", "refs": [0], "values": [0.96]},
            {"symbol": "H", "refs": [0, 1], "values": [0.96, 104.5]},
        ]
        lines = zmatrix_cards(rows)
        self.assertEqual(lines[0].split(), ["O"])
        self.assertEqual(
            lines[2].split(), ["H", "1", "0.96000000", "2", "104.50000000"]
        )

    def test_variables_follow_a_blank_card(self):
        rows = [
            {"symbol": "O", "refs": [], "values": []},
            {"symbol": "H", "refs": [0], "values": [0.96]},
        ]
        lines = zmatrix_cards(rows, variables=True)
        self.assertEqual(lines[1].split(), ["H", "1", "B2"])
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3].split(), ["B2", "0.96000000"])

    def test_title_is_cut_to_80_columns(self):
        title = data_group("x" * 200, [])[1]
        self.assertEqual(len(title), 80)

    def test_empty_title_gets_a_name(self):
        self.assertEqual(data_group("  ", [])[1], "GAMESS Job")

    def test_c1_card_directly_followed_by_atoms(self):
        lines = data_group("t", ["O 8.0 0 0 0"])
        self.assertEqual(lines[2:4], ["C1", "O 8.0 0 0 0"])

    def test_extra_is_copied_after_data(self):
        text = build_input(
            "t",
            " $BASIS GBASIS=STO $END",
            [],
            0,
            1,
            10,
            0,
            "UNIQUE",
            " $HESS\n 1\n $END\n",
        )
        self.assertLess(text.index("$DATA"), text.index("$HESS"))
        self.assertIn(" $HESS\n 1\n $END\n", text)


class TestSpherical(unittest.TestCase):
    def test_modern_sets_are_named(self):
        for name in ("CCD", "ACCT", "CCTC", "PCseg-1", "APCseg-2", "SPK-DZP", "KTZV"):
            self.assertTrue(needs_spherical(name), name)

    def test_classic_sets_are_not(self):
        for name in ("STO", "N31", "N311", "TZV", "MINI", "MC", "DH", None):
            self.assertFalse(needs_spherical(name), name)


class TestCheckInput(unittest.TestCase):
    def _notes(self, text, mult=1, electrons=None, memddi=0, extra=""):
        return " ".join(check_input(parse_groups(text), mult, electrons, memddi, extra))

    def test_a_plain_job_has_no_notes(self):
        self.assertEqual(
            self._notes(" $CONTRL SCFTYP=RHF RUNTYP=ENERGY $END", 1, 10), ""
        )

    def test_rhf_with_open_shell(self):
        self.assertIn("MULT=1", self._notes(" $CONTRL SCFTYP=RHF $END", 3))

    def test_default_scftyp_is_rhf(self):
        self.assertIn("MULT=1", self._notes(" $CONTRL RUNTYP=ENERGY $END", 3))

    def test_parity(self):
        self.assertIn("multiplicity", self._notes(" $CONTRL SCFTYP=ROHF $END", 2, 10))

    def test_modern_basis_without_ispher(self):
        self.assertIn("ISPHER", self._notes(" $BASIS GBASIS=PCseg-1 $END"))
        self.assertNotIn(
            "ISPHER", self._notes(" $CONTRL ISPHER=1 $END\n $BASIS GBASIS=PCseg-1 $END")
        )

    def test_cc_without_memddi(self):
        self.assertIn("needs MEMDDI", self._notes(" $CONTRL CCTYP=CCSD $END"))
        self.assertNotIn("MEMDDI", self._notes(" $CONTRL CCTYP=CCSD $END", memddi=10))

    def test_serial_cc_types(self):
        self.assertIn("one core only", self._notes(" $CONTRL CCTYP=CR-CC $END"))
        self.assertNotIn("one core only", self._notes(" $CONTRL CCTYP=CCSD(T) $END"))

    def test_one_correlation_method(self):
        for text in (
            " $CONTRL DFTTYP=B3LYP CCTYP=CCSD $END",
            " $CONTRL DFTTYP=B3LYP MPLEVL=2 $END",
            " $CONTRL MPLEVL=2 CCTYP=CCSD $END",
        ):
            self.assertIn("at most one", self._notes(text), text)
        self.assertNotIn("at most one", self._notes(" $CONTRL MPLEVL=2 $END"))

    def test_nmr(self):
        self.assertIn("no DFT", self._notes(" $CONTRL RUNTYP=NMR DFTTYP=B3LYP $END"))
        self.assertIn("one core", self._notes(" $CONTRL RUNTYP=NMR $END"))
        self.assertIn(
            "DIRSCF", self._notes(" $CONTRL RUNTYP=NMR $END\n $SCF DIRSCF=.TRUE. $END")
        )

    def test_raman_needs_both_groups(self):
        self.assertIn(
            "$DIPDR", self._notes(" $CONTRL RUNTYP=RAMAN $END", extra=" $HESS\n $END")
        )
        self.assertNotIn(
            "$DIPDR",
            self._notes(
                " $CONTRL RUNTYP=RAMAN $END", extra=" $HESS\n $END\n $DIPDR\n $END"
            ),
        )

    def test_sadpoint_without_hessian(self):
        self.assertIn("HESS=CALC", self._notes(" $CONTRL RUNTYP=SADPOINT $END"))
        self.assertNotIn(
            "HESS=CALC",
            self._notes(" $CONTRL RUNTYP=SADPOINT $END\n $STATPT HESS=CALC $END"),
        )


class TestBuilderFields(unittest.TestCase):
    def test_unknown_keys_survive(self):
        groups = parse_groups(" $CONTRL RUNTYP=ENERGY MAXIT=50 $END\n $ZZZ A=1 $END")
        out = apply_fields(groups, {("CONTRL", "RUNTYP"): "OPTIMIZE"})
        self.assertEqual(get_option(out, "CONTRL", "MAXIT"), "50")
        self.assertEqual(get_option(out, "ZZZ", "A"), "1")

    def test_empty_value_removes_and_empty_group_goes(self):
        groups = parse_groups(" $PCM SOLVNT=WATER $END")
        self.assertEqual(apply_fields(groups, {("PCM", "SOLVNT"): ""}), [])

    def test_spherical_is_set_for_modern_basis(self):
        out = normalize_for_builder([("BASIS", [("GBASIS", "ACCD")])])
        self.assertEqual(get_option(out, "CONTRL", "ISPHER"), "1")

    def test_sadpoint_computes_its_hessian(self):
        out = normalize_for_builder([("CONTRL", [("RUNTYP", "SADPOINT")])])
        self.assertEqual(get_option(out, "STATPT", "HESS"), "CALC")

    def test_sadpoint_keeps_a_chosen_hessian(self):
        out = normalize_for_builder(
            [("CONTRL", [("RUNTYP", "SADPOINT")]), ("STATPT", [("HESS", "READ")])]
        )
        self.assertEqual(get_option(out, "STATPT", "HESS"), "READ")


if __name__ == "__main__":
    unittest.main()
