"""Reading a GAMESS input back: settings, atoms and honest notes. No Qt."""

import math
import os
import tempfile
import unittest

from gamess_input_generator_pro.group_builder import (
    BOHR_ANGSTROM,
    get_option,
    parse_groups,
)
from gamess_input_generator_pro.input_loading import (
    internal_rows,
    parse_input,
    read_input,
    write_input,
)

CARTESIAN = """ $CONTRL SCFTYP=UHF RUNTYP=ENERGY ICHARG=-1 MULT=2 COORD=UNIQUE $END
 $SYSTEM MWORDS=64 MEMDDI=8 $END
 $BASIS GBASIS=N31 NGAUSS=6 $END
 $DATA
My title
C1
O       8.0     0.0     0.0     0.0
H       1.0     0.0     0.0     1.0
 $END
"""


class TestParseInput(unittest.TestCase):
    def test_settings(self):
        settings, rows, notes = parse_input(CARTESIAN)
        self.assertEqual(settings["charge"], -1)
        self.assertEqual(settings["mult"], 2)
        self.assertEqual(settings["mwords"], 64)
        self.assertEqual(settings["memddi"], 8)
        self.assertEqual(settings["title"], "My title")
        self.assertEqual(notes, [])
        self.assertEqual(rows[1], ("H", 0.0, 0.0, 1.0))

    def test_generated_keywords_leave_the_groups_box(self):
        groups = parse_groups(parse_input(CARTESIAN)[0]["groups"])
        for name, key in (
            ("CONTRL", "ICHARG"),
            ("CONTRL", "MULT"),
            ("CONTRL", "COORD"),
        ):
            self.assertIsNone(get_option(groups, name, key))
        self.assertIsNone(get_option(groups, "SYSTEM", "MWORDS"))
        self.assertEqual(get_option(groups, "CONTRL", "SCFTYP"), "UHF")

    def test_foreign_files_raise(self):
        for text in ("! B3LYP def2-SVP\n* xyz 0 1\nO 0 0 0\n*\n", "%chk=a\n# hf\n", ""):
            with self.assertRaisesRegex(ValueError, "not a GAMESS input"):
                parse_input(text, "other.inp")

    def test_contrl_alone_is_kept_with_a_note(self):
        settings, rows, notes = parse_input(" $CONTRL RUNTYP=ENERGY $END\n")
        self.assertEqual(rows, [])
        self.assertIn("$DATA", notes[0])
        self.assertIn("RUNTYP", settings["groups"])

    def test_data_alone_counts(self):
        rows = parse_input(" $DATA\nt\nC1\nH 1.0 0 0 0\n $END\n")[1]
        self.assertEqual(len(rows), 1)

    def test_group_case_is_ignored(self):
        self.assertEqual(
            len(parse_input(CARTESIAN.lower().replace("my title", "t"))[1]), 2
        )

    def test_negative_znuc_is_a_ghost(self):
        rows = parse_input(" $DATA\nt\nC1\nGH -6.0 1 2 3\n $END\n")[1]
        self.assertEqual(rows[0], ("C:", 1.0, 2.0, 3.0))

    def test_zero_znuc_is_a_dummy(self):
        self.assertEqual(
            parse_input(" $DATA\nt\nC1\nBQ 0.0 1 2 3\n $END\n")[1][0][0], "X"
        )

    def test_label_does_not_decide_the_element(self):
        self.assertEqual(
            parse_input(" $DATA\nt\nC1\nCARBON1 6.0 1 2 3\n $END\n")[1][0][0], "C"
        )

    def test_inline_basis_cards_are_not_atoms(self):
        text = """ $CONTRL RUNTYP=ENERGY $END
 $DATA
t
C1
O 8.0 0 0 0
 N31 6

H 1.0 0 0 1
 S 3
 1 18.7 0.03
 2 2.8 0.2
 3 0.6 0.8

 $END
"""
        rows = parse_input(text)[1]
        self.assertEqual([row[0] for row in rows], ["O", "H"])

    def test_bohr_is_converted_to_angstrom(self):
        text = " $CONTRL UNITS=BOHR $END\n $DATA\nt\nC1\nH 1.0 0 0 1.0\n $END\n"
        self.assertAlmostEqual(parse_input(text)[1][0][3], BOHR_ANGSTROM)

    def test_symmetry_keeps_the_text_without_a_structure(self):
        text = " $DATA\nt\nCNV 2\n\nO 8.0 0 0 0\nH 1.0 0 0.7 0.5\n $END\n"
        _, rows, notes = parse_input(text)
        self.assertEqual(rows, [])
        self.assertIn("symmetry-unique", notes[0])

    def test_other_coord_styles_keep_the_text(self):
        for coord in ("HINT", "ZMTMPC", "PRINAXIS", "FRAGONLY"):
            text = f" $CONTRL COORD={coord} $END\n $DATA\nt\nC1\nO 8.0 0 0 0\n $END\n"
            _, rows, notes = parse_input(text)
            self.assertEqual(rows, [], coord)
            self.assertIn(coord, notes[0])

    def test_free_form_groups_go_to_extra(self):
        text = CARTESIAN + " $HESS\nENERGY IS -1.0 E(NUC) IS 2.0\n 1 1 1.0\n $END\n"
        settings = parse_input(text)[0]
        self.assertIn("$HESS", settings["extra"])
        self.assertIn(" 1 1 1.0", settings["extra"])
        self.assertNotIn("HESS", settings["groups"])

    def test_bad_number_is_a_note(self):
        notes = parse_input(" $CONTRL ICHARG=X $END\n $DATA\nt\nC1\n $END\n")[2]
        self.assertTrue(any("ICHARG" in note for note in notes))


class TestZMatrix(unittest.TestCase):
    PLAIN = """ $CONTRL COORD=ZMT $END
 $DATA
t
C1
O
O 1 1.45
H 1 0.97 2 100.0
H 2 0.97 1 100.0 3 115.0
 $END
"""
    VARIABLES = """ $CONTRL COORD=ZMT $END
 $DATA
t
C1
O
O 1 B2
H 1 B3 2 A3
H 2 B3 1 A3 3 D4

B2 1.45
B3 0.97
A3 100.0
D4 115.0
 $END
"""

    @staticmethod
    def _distance(a, b):
        return math.dist(a[1:], b[1:])

    @staticmethod
    def _dihedral(rows):
        def sub(a, b):
            return [x - y for x, y in zip(a[1:], b[1:])]

        def cross(a, b):
            return [
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            ]

        p = cross(sub(rows[2], rows[0]), sub(rows[1], rows[0]))
        q = cross(sub(rows[3], rows[1]), sub(rows[0], rows[1]))
        dot = -sum(x * y for x, y in zip(p, q))
        norm = math.hypot(*p) * math.hypot(*q)
        return math.degrees(math.acos(dot / norm))

    def test_plain_rows_give_the_geometry(self):
        settings, rows, _ = parse_input(self.PLAIN)
        self.assertEqual(settings["coord_format"], "Z-Matrix")
        self.assertAlmostEqual(self._distance(rows[0], rows[1]), 1.45)
        self.assertAlmostEqual(self._distance(rows[3], rows[1]), 0.97)
        self.assertAlmostEqual(self._dihedral(rows), 115.0, places=4)

    def test_variables_give_the_same_geometry(self):
        settings, rows, _ = parse_input(self.VARIABLES)
        self.assertEqual(settings["coord_format"], "Z-Matrix (variables)")
        for one, two in zip(rows, parse_input(self.PLAIN)[1]):
            for a, b in zip(one[1:], two[1:]):
                self.assertAlmostEqual(a, b)

    def test_undefined_variable_is_a_note_not_a_crash(self):
        text = self.VARIABLES.replace("B2 1.45\n", "")
        _, rows, notes = parse_input(text)
        self.assertEqual(rows, [])
        self.assertIn("B2", notes[0])

    def test_units_apply_to_internal_coordinates(self):
        text = self.PLAIN.replace("COORD=ZMT", "COORD=ZMT UNITS=BOHR").replace(
            "1.45", str(1.45 / BOHR_ANGSTROM)
        )
        text = text.replace(" 0.97", " " + str(0.97 / BOHR_ANGSTROM))
        rows = parse_input(text)[1]
        self.assertAlmostEqual(self._distance(rows[0], rows[1]), 1.45)
        self.assertAlmostEqual(self._dihedral(rows), 115.0, places=4)

    def test_negative_distance_is_refused(self):
        with self.assertRaises(ValueError):
            internal_rows(["O", "H 1 -1.0"])


class TestFiles(unittest.TestCase):
    def test_write_then_read(self):
        path = os.path.join(tempfile.gettempdir(), "round_trip.inp")
        write_input(path, CARTESIAN)
        self.assertEqual(read_input(path).replace("\r\n", "\n"), CARTESIAN)

    def test_oversized_file_is_refused(self):
        path = os.path.join(tempfile.gettempdir(), "big.inp")
        with open(path, "wb") as handle:
            handle.write(b" " * (16 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "16 MB"):
            read_input(path)


if __name__ == "__main__":
    unittest.main()
