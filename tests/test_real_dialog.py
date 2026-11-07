"""The real window under real Qt: every button pressed, every claim driven through it."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QInputDialog,
        QMessageBox,
        QPushButton,
    )
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolTransforms
except ImportError:
    if os.environ.get("REQUIRE_REAL_QT") == "1":
        raise
    raise unittest.SkipTest("needs PySide6 and RDKit") from None

from gamess_input_generator_pro import main_dialog as M
from gamess_input_generator_pro.group_builder import get_option, parse_groups
from gamess_input_generator_pro.input_loading import molecule_from_rows, parse_input

INPUTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verified_inputs")
APP = QApplication.instance() or QApplication([])


def _mol(smiles, seed=7):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(mol, randomSeed=seed)
    return mol


class DialogCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.errors = []
        hook = mock.patch.object(
            sys, "excepthook", lambda kind, value, tb: self.errors.append(value)
        )
        hook.start()
        self.addCleanup(hook.stop)
        for target, name, value in (
            (M, "SETTINGS_FILE", os.path.join(self.tmp, "settings.json")),
            (QMessageBox, "warning", mock.Mock()),
            (QMessageBox, "critical", mock.Mock()),
            (
                QMessageBox,
                "question",
                mock.Mock(return_value=QMessageBox.StandardButton.Yes),
            ),
            (
                QFileDialog,
                "getSaveFileName",
                mock.Mock(return_value=(os.path.join(self.tmp, "job.inp"), "")),
            ),
            (QFileDialog, "getOpenFileName", mock.Mock(return_value=("", ""))),
            (QInputDialog, "getText", mock.Mock(return_value=("Mine", True))),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def dialog(self, mol=None, **kwargs):
        mol = mol if mol is not None else _mol("O")
        settings = kwargs.pop("settings", {})
        dlg = M.GamessSetupDialogPro(
            None, mol=mol, persistent_settings=settings, get_molecule=lambda: mol, **kwargs
        )
        self.addCleanup(dlg.deleteLater)
        return dlg

    @staticmethod
    def text(dlg):
        return dlg.preview_text.toPlainText()

    def set_groups(self, dlg, text):
        dlg.keywords_edit.setPlainText(text)
        return self.text(dlg)


class TestPreview(DialogCase):
    def test_default_input_reads_back(self):
        dlg = self.dialog()
        settings, rows, notes = parse_input(self.text(dlg))
        self.assertEqual(notes, [])
        self.assertEqual(len(rows), 3)
        self.assertEqual(settings["charge"], 0)
        self.assertEqual(settings["mult"], 1)
        self.assertIn("MWORDS=100", self.text(dlg))

    def test_cards_stay_inside_80_columns(self):
        dlg = self.dialog()
        self.set_groups(
            dlg,
            " $CONTRL SCFTYP=RHF RUNTYP=OPTIMIZE DFTTYP=B3LYP MAXIT=200 NPRINT=7 "
            "ISPHER=1 MPLEVL=0 $END\n",
        )
        for line in self.text(dlg).splitlines():
            self.assertLessEqual(len(line), 80, line)

    def test_memory_controls_reach_system_group(self):
        dlg = self.dialog()
        dlg.mwords_spin.setValue(250)
        dlg.memddi_spin.setValue(40)
        groups = parse_groups(self.text(dlg).split(" $DATA")[0])
        self.assertEqual(get_option(groups, "SYSTEM", "MWORDS"), "250")
        self.assertEqual(get_option(groups, "SYSTEM", "MEMDDI"), "40")
        self.assertEqual(dlg.mwords_hint.text(), "= 2.0 GB")

    def test_charge_from_the_molecule(self):
        dlg = self.dialog(_mol("[OH-]"))
        self.assertEqual(parse_input(self.text(dlg))[0]["charge"], -1)

    def test_radical_gets_multiplicity_and_rohf(self):
        mol = Chem.MolFromSmiles("[CH3]")
        mol = Chem.AddHs(mol)
        AllChem.EmbedMolecule(mol, randomSeed=3)
        dlg = self.dialog(mol)
        settings = parse_input(self.text(dlg))[0]
        self.assertEqual(settings["mult"], 2)
        self.assertEqual(get_option(parse_groups(settings["groups"]), "CONTRL", "SCFTYP"), "ROHF")

    def test_title_goes_to_data_and_is_cut(self):
        dlg = self.dialog()
        dlg.comment_edit.setText("t" * 100)
        self.assertEqual(parse_input(self.text(dlg))[0]["title"], "t" * 80)

    def test_extra_groups_are_copied_as_written(self):
        dlg = self.dialog()
        dlg.tail_edit.setPlainText(" $HESS\n 1  1 1.0\n $END\n")
        self.assertTrue(self.text(dlg).endswith(" $HESS\n 1  1 1.0\n $END\n"))
        self.assertLess(self.text(dlg).index("$DATA"), self.text(dlg).index("$HESS"))

    def test_templates_insert_their_groups(self):
        dlg = self.dialog()
        for index in range(1, dlg.tail_template_combo.count()):
            dlg.tail_edit.clear()
            dlg.tail_template_combo.setCurrentIndex(index)
            dlg.insert_tail_template()
            self.assertIn("$", dlg.tail_edit.toPlainText())

    def test_units_bohr_scales_the_coordinates(self):
        dlg = self.dialog()
        before = parse_input(self.text(dlg))[1]
        self.set_groups(dlg, " $CONTRL RUNTYP=ENERGY UNITS=BOHR $END\n")
        after = parse_input(self.text(dlg))[1]
        for one, two in zip(before, after):
            self.assertAlmostEqual(one[3], two[3], places=6)
        self.assertIn("UNITS=BOHR", self.text(dlg))

    def test_bad_groups_show_why_and_cannot_be_saved(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL RUNTYP=ENERGY\n")
        self.assertIn("! Invalid input", self.text(dlg))
        dlg.save_file()
        QMessageBox.critical.assert_called_once()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "job.inp")))


class TestWarnings(DialogCase):
    def shown(self, dlg):
        return dlg.warnings_label.text() if not dlg.warnings_label.isHidden() else ""

    def test_plain_job_has_none(self):
        self.assertEqual(self.shown(self.dialog()), "")

    def test_cc_without_distributed_memory(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL CCTYP=CCSD(T) $END\n")
        self.assertIn("needs MEMDDI", self.shown(dlg))
        dlg.memddi_spin.setValue(50)
        self.assertNotIn("needs MEMDDI", self.shown(dlg))

    def test_bad_parity(self):
        dlg = self.dialog()
        dlg.mult_spin.setValue(2)
        self.assertIn("multiplicity", self.shown(dlg))

    def test_raman_asks_for_its_groups(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL RUNTYP=RAMAN $END\n")
        self.assertIn("$DIPDR", self.shown(dlg))

    def test_open_shell_turns_rhf_into_rohf(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL SCFTYP=RHF RUNTYP=ENERGY $END\n")
        dlg.mult_spin.setValue(3)
        self.assertIn("SCFTYP=ROHF", dlg.keywords_edit.toPlainText())


class TestCoordinateFormats(DialogCase):
    def bond_lengths(self, rows):
        return [
            rdMolTransforms.GetBondLength(molecule_from_rows(rows).GetConformer(), 0, i)
            for i in range(1, len(rows))
        ]

    def test_zmatrix_reproduces_the_geometry(self):
        mol = _mol("CO")
        dlg = self.dialog(mol)
        cartesian = parse_input(self.text(dlg))[1]
        for name, style in (
            (M.COORD_ZMATRIX, "Z-Matrix"),
            (M.COORD_ZMATRIX_VARIABLES, "Z-Matrix (variables)"),
        ):
            dlg.coord_format_combo.setCurrentText(name)
            settings, rows, notes = parse_input(self.text(dlg))
            self.assertEqual(settings["coord_format"], style)
            self.assertEqual(notes, [])
            self.assertIn("COORD=ZMT", self.text(dlg))
            for one, two in zip(self.bond_lengths(cartesian), self.bond_lengths(rows)):
                self.assertAlmostEqual(one, two, places=5)

    def test_linear_molecule_falls_back_to_cartesian(self):
        mol = _mol("O=C=O")
        conf = mol.GetConformer()
        for index, z in enumerate((-1.16, 0.0, 1.16)):
            conf.SetAtomPosition(index, (0.0, 0.0, z))
        dlg = self.dialog(mol)
        dlg.coord_format_combo.setCurrentText(M.COORD_ZMATRIX)
        self.assertIn("COORD=UNIQUE", self.text(dlg))
        self.assertIn("Using Cartesian", dlg.coord_notice.text())
        self.assertFalse(dlg.coord_notice.isHidden())

    def test_ghost_keeps_its_basis_in_cartesian(self):
        for custom in ("H:", "H-Bq"):
            mol = _mol("O")
            mol.GetAtomWithIdx(2).SetProp("custom_symbol", custom)
            dlg = self.dialog(mol)
            self.assertEqual(parse_input(self.text(dlg))[1][2][0], "H:")

    def test_ghost_carries_no_electrons(self):
        mol = _mol("O")
        mol.GetAtomWithIdx(2).SetProp("custom_symbol", "H:")
        self.assertEqual(M._electron_count(mol, 0), 9)

    def test_plain_dummy_has_zero_znuc(self):
        mol = _mol("O")
        mol.GetAtomWithIdx(2).SetProp("custom_symbol", "Bq")
        dlg = self.dialog(mol)
        self.assertEqual(parse_input(self.text(dlg))[1][2][0], "X")

    def test_zmatrix_with_ghost_falls_back(self):
        mol = _mol("O")
        mol.GetAtomWithIdx(2).SetProp("custom_symbol", "H:")
        dlg = self.dialog(mol)
        dlg.coord_format_combo.setCurrentText(M.COORD_ZMATRIX)
        self.assertIn("COORD=UNIQUE", self.text(dlg))
        self.assertIn("Ghost", dlg.coord_notice.text())


class TestBuilder(DialogCase):
    def builder(self, dlg):
        dlg.open_keyword_builder()
        self.addCleanup(dlg.builder_dialog.close)
        return dlg.builder_dialog

    def test_every_choice_of_every_control_writes_its_keyword(self):
        builder = self.builder(self.dialog())
        for (group, key), (widget, kind, choices) in builder.widgets.items():
            if isinstance(widget, QComboBox):
                for index in range(1, widget.count()):
                    widget.setCurrentIndex(index)
                    groups = parse_groups(builder.get_groups())
                    self.assertEqual(
                        get_option(groups, group, key), widget.itemData(index), key
                    )
                widget.setCurrentIndex(0)
                self.assertIsNone(
                    get_option(parse_groups(builder.get_groups()), group, key), key
                )
            else:
                self.assertIsInstance(widget, QCheckBox)
                widget.setChecked(True)
                self.assertIsNotNone(
                    get_option(parse_groups(builder.get_groups()), group, key), key
                )
                widget.setChecked(False)
                self.assertIsNone(
                    get_option(parse_groups(builder.get_groups()), group, key), key
                )

    def test_controls_show_what_the_text_says(self):
        dlg = self.dialog()
        self.set_groups(
            dlg,
            " $CONTRL RUNTYP=HESSIAN DFTTYP=PBE0 NPRINT=7 $END\n"
            " $SCF DIRSCF=.T. $END\n $PCM SOLVNT=THF $END\n",
        )
        builder = self.builder(dlg)
        self.assertEqual(builder.widgets[("CONTRL", "RUNTYP")][0].currentData(), "HESSIAN")
        self.assertEqual(builder.widgets[("CONTRL", "DFTTYP")][0].currentData(), "PBE0")
        self.assertTrue(builder.widgets[("CONTRL", "NPRINT")][0].isChecked())
        self.assertTrue(builder.widgets[("SCF", "DIRSCF")][0].isChecked())
        self.assertEqual(builder.widgets[("PCM", "SOLVNT")][0].currentData(), "THF")

    def test_keywords_without_a_control_survive_the_round_trip(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL RUNTYP=ENERGY MAXIT=77 $END\n $ZMAT DLC=.T. $END\n")
        builder = self.builder(dlg)
        builder.widgets[("CONTRL", "RUNTYP")][0].setCurrentText("GRADIENT")
        builder.accept()
        text = dlg.keywords_edit.toPlainText()
        self.assertIn("RUNTYP=GRADIENT", text)
        self.assertIn("MAXIT=77", text)
        self.assertIn("$ZMAT DLC=.T.", text)

    def test_value_outside_the_list_is_kept(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $STATPT NSTEP=77 $END\n")
        builder = self.builder(dlg)
        self.assertEqual(builder.widgets[("STATPT", "NSTEP")][0].currentData(), "77")
        self.assertIn("NSTEP=77", builder.get_groups())

    def test_modern_basis_turns_ispher_on_and_off(self):
        builder = self.builder(self.dialog())
        basis = builder.widgets[("BASIS", "GBASIS")][0]
        basis.setCurrentText("PCseg-1")
        self.assertIn("ISPHER=1", builder.get_groups())
        builder.load_groups(builder.get_groups())
        basis.setCurrentText("N31")
        self.assertNotIn("ISPHER", builder.get_groups())

    def test_sadpoint_computes_its_hessian(self):
        builder = self.builder(self.dialog())
        builder.widgets[("CONTRL", "RUNTYP")][0].setCurrentText("SADPOINT")
        self.assertIn("HESS=CALC", builder.get_groups())

    def test_dispersion_choice_writes_idcver(self):
        builder = self.builder(self.dialog())
        dispersion = builder.widgets[("DFT", "IDCVER")][0]
        dispersion.setCurrentText("D3(BJ)")
        self.assertIn("$DFT IDCVER=4", builder.get_groups())

    def test_esp_box_writes_both_groups_and_reads_them_back(self):
        builder = self.builder(self.dialog())
        builder.esp_check.setChecked(True)
        text = builder.get_groups()
        self.assertIn("$ELPOT IEPOT=1 WHERE=PDC OUTPUT=BOTH", text)
        self.assertIn("$PDC PTSEL=CHELPG CONSTR=CHARGE", text)
        builder.esp_check.setChecked(False)
        builder.load_groups(text)
        self.assertTrue(builder.esp_check.isChecked())

    def test_cancel_changes_nothing(self):
        dlg = self.dialog()
        before = dlg.keywords_edit.toPlainText()
        builder = self.builder(dlg)
        builder.widgets[("CONTRL", "RUNTYP")][0].setCurrentText("NMR")
        builder.reject()
        self.assertEqual(dlg.keywords_edit.toPlainText(), before)

    def test_unreadable_groups_do_not_open_it(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL RUNTYP=ENERGY\n")
        dlg.open_keyword_builder()
        QMessageBox.warning.assert_called_once()
        self.assertIsNone(dlg.builder_dialog)


class TestFiles(DialogCase):
    def test_save_writes_the_preview(self):
        dlg = self.dialog()
        dlg.save_file()
        with open(os.path.join(self.tmp, "job.inp"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().replace("\r\n", "\n"), self.text(dlg))
        self.assertIn("job.inp", dlg.windowTitle())

    def test_default_name_has_the_run_type_suffix(self):
        expected = {
            "OPTIMIZE": "-opt",
            "SADPOINT": "-ts",
            "HESSIAN": "-freq",
            "RAMAN": "-raman",
            "NMR": "-nmr",
            "GRADIENT": "-grad",
            "ENERGY": "-sp",
        }
        dlg = self.dialog(filename="water.pmeprj")
        for runtyp, suffix in expected.items():
            self.set_groups(dlg, f" $CONTRL RUNTYP={runtyp} $END\n")
            dlg.save_file()
            offered = QFileDialog.getSaveFileName.call_args[0][2]
            self.assertTrue(offered.endswith(f"water{suffix}.inp"), offered)
        self.set_groups(dlg, " $CONTRL RUNTYP=ENERGY TDDFT=EXCITE $END\n")
        self.assertEqual(dlg._auto_suffix(), "-td")

    def test_auto_suffix_can_be_off(self):
        dlg = self.dialog(filename="water.pmeprj")
        dlg.auto_suffix_cb.setChecked(False)
        dlg.save_file()
        self.assertTrue(QFileDialog.getSaveFileName.call_args[0][2].endswith("water.inp"))

    def test_every_verified_input_loads_verbatim(self):
        shown = []
        for name in sorted(os.listdir(INPUTS)):
            if not name.endswith(".inp"):
                continue
            path = os.path.join(INPUTS, name)
            dlg = self.dialog(display_molecule=shown.append)
            self.assertTrue(dlg.load_input_file(path), name)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(self.text(dlg), handle.read(), name)
            self.assertFalse(dlg._is_modified(), name)
            self.assertIs(shown[-1], dlg.mol, name)
        self.assertGreater(len(shown), 30)

    def test_foreign_file_is_refused_and_changes_nothing(self):
        path = os.path.join(self.tmp, "orca.inp")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("! B3LYP def2-SVP\n* xyz 0 1\nO 0 0 0\n*\n")
        dlg = self.dialog()
        before = self.text(dlg)
        self.assertFalse(dlg.load_input_file(path))
        QMessageBox.warning.assert_called_once()
        self.assertEqual(self.text(dlg), before)

    def test_recover_conditions_from_edited_text(self):
        dlg = self.dialog()
        edited = self.text(dlg).replace("RUNTYP=OPTIMIZE", "RUNTYP=HESSIAN").replace("MWORDS=100", "MWORDS=321")
        dlg.preview_text.setPlainText(edited)
        self.assertTrue(dlg._text_override)
        dlg.recover_input_conditions()
        self.assertIn("RUNTYP=HESSIAN", dlg.keywords_edit.toPlainText())
        self.assertEqual(dlg.mwords_spin.value(), 321)
        self.assertEqual(self.text(dlg), edited)

    def test_refresh_regenerates_from_the_settings(self):
        dlg = self.dialog()
        generated = self.text(dlg)
        dlg.preview_text.setPlainText(generated + "! edited\n")
        dlg.refresh_input_preview()
        self.assertEqual(self.text(dlg), generated)
        self.assertFalse(dlg._text_override)

    def test_closing_with_changes_asks_and_can_cancel(self):
        dlg = self.dialog()
        dlg.save_file()
        dlg.preview_text.setPlainText(self.text(dlg) + "! edited\n")
        self.assertTrue(dlg._is_modified())
        QMessageBox.question.return_value = QMessageBox.StandardButton.Cancel
        self.assertFalse(dlg._confirm_discard())
        QMessageBox.question.return_value = QMessageBox.StandardButton.Save
        self.assertTrue(dlg._confirm_discard())
        with open(os.path.join(self.tmp, "job.inp"), encoding="utf-8") as handle:
            self.assertIn("! edited", handle.read())

    def test_project_settings_restore_the_window(self):
        settings = {}
        dlg = self.dialog(settings=settings)
        dlg.mwords_spin.setValue(222)
        dlg.tail_edit.setPlainText(" $HESS\n $END\n")
        dlg.coord_format_combo.setCurrentText(M.COORD_ZMATRIX)
        reopened = self.dialog(settings=json.loads(json.dumps(settings)))
        self.assertEqual(reopened.mwords_spin.value(), 222)
        self.assertIn("$HESS", reopened.tail_edit.toPlainText())
        self.assertEqual(reopened.coord_format_combo.currentText(), M.COORD_ZMATRIX)

    def test_detached_project_keeps_the_text(self):
        dlg = self.dialog()
        dlg.detach_project()
        self.assertIn("Detached", dlg.windowTitle())
        self.assertIn("previous project", dlg.input_notice.text())


class TestPresets(DialogCase):
    def test_save_apply_delete(self):
        dlg = self.dialog()
        self.set_groups(dlg, " $CONTRL RUNTYP=GRADIENT $END\n")
        dlg.mwords_spin.setValue(77)
        dlg.save_preset_dialog()
        self.assertEqual(dlg.preset_combo.currentText(), "Mine")
        with open(M.SETTINGS_FILE, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["Mine"]["mwords"], 77)
        dlg.preset_combo.setCurrentText("Default")
        self.assertIn("OPTIMIZE", dlg.keywords_edit.toPlainText())
        dlg.preset_combo.setCurrentText("Mine")
        self.assertIn("GRADIENT", dlg.keywords_edit.toPlainText())
        dlg.delete_preset()
        self.assertEqual(dlg.preset_combo.findText("Mine"), -1)

    def test_default_cannot_be_deleted(self):
        dlg = self.dialog()
        dlg.preset_combo.setCurrentText("Default")
        dlg.delete_preset()
        QMessageBox.warning.assert_called_once()
        self.assertNotEqual(dlg.preset_combo.findText("Default"), -1)

    def test_auto_suffix_setting_is_remembered(self):
        dlg = self.dialog()
        dlg.auto_suffix_cb.setChecked(False)
        self.assertFalse(self.dialog().auto_suffix_cb.isChecked())


class FakeJobManager:
    def __init__(self, accept=True):
        self.accept = accept
        self.calls = []

    def submit_file(self, path, name=""):
        self.calls.append((path, name))
        return self.accept


class TestSubmit(DialogCase):
    def host(self, module):
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        host.plugin_manager = mock.Mock(plugins=[{"name": "Job Manager", "module": module}])
        self.addCleanup(host.deleteLater)
        return host

    def test_button_hidden_without_job_manager(self):
        self.assertTrue(self.dialog().submit_btn.isHidden())

    def test_submit_saves_then_hands_the_file_over(self):
        manager = FakeJobManager()
        mol = _mol("O")
        dlg = M.GamessSetupDialogPro(self.host(manager), mol=mol, get_molecule=lambda: mol)
        self.assertFalse(dlg.submit_btn.isHidden())
        dlg.submit_to_cluster()
        self.assertEqual(manager.calls, [(os.path.join(self.tmp, "job.inp"), "job")])

    def test_refusal_is_reported(self):
        manager = FakeJobManager(accept=False)
        mol = _mol("O")
        dlg = M.GamessSetupDialogPro(self.host(manager), mol=mol, get_molecule=lambda: mol)
        dlg.submit_to_cluster()
        QMessageBox.warning.assert_called_once()


class TestEveryButton(DialogCase):
    def press_all(self, window):
        for button in window.findChildren(QPushButton):
            if button.isEnabled():
                button.click()
                APP.processEvents()

    def test_main_window(self):
        dlg = self.dialog()
        dlg.tail_template_combo.setCurrentIndex(1)
        self.press_all(dlg)
        QMessageBox.critical.assert_not_called()

    def test_builder_window(self):
        dlg = self.dialog()
        dlg.open_keyword_builder()
        self.press_all(dlg.builder_dialog)
        QMessageBox.critical.assert_not_called()

    def test_every_control_in_the_main_window_keeps_a_valid_preview(self):
        dlg = self.dialog()
        for combo in dlg.findChildren(QComboBox):
            for index in range(combo.count()):
                combo.setCurrentIndex(index)
                APP.processEvents()
        self.assertNotIn("! Invalid", self.text(dlg))


class TestPluginEntry(DialogCase):
    def context(self, mol):
        import gamess_input_generator_pro as P

        windows = {}
        context = mock.MagicMock()
        context.current_molecule = mol
        context.get_main_window.return_value = None
        context.get_window.side_effect = windows.get
        context.register_window.side_effect = windows.__setitem__
        P.current_settings.clear()
        P.current_settings.update(P.get_default_settings())
        P.initialize(context)
        self.addCleanup(lambda: [w.deleteLater() for w in windows.values()])
        return P, context, windows

    def test_opener_takes_gamess_and_refuses_orca(self):
        P, context, windows = self.context(_mol("O"))
        args = context.register_file_opener.call_args
        self.assertEqual(args[0][0], ".inp")
        self.assertGreater(args[1]["priority"], 100)
        opener = args[0][1]
        orca = os.path.join(self.tmp, "orca.inp")
        with open(orca, "w", encoding="utf-8") as handle:
            handle.write("! B3LYP def2-SVP\n* xyz 0 1\nO 0 0 0\n*\n")
        with self.assertRaises(ValueError):
            opener(orca)
        self.assertEqual(windows, {})
        opener(os.path.join(INPUTS, "rhf_energy.inp"))
        self.assertIn("rhf_energy", windows["dialog"].windowTitle())

    def test_drop_handler_takes_only_gamess_inputs(self):
        P, context, _ = self.context(_mol("O"))
        handle_drop = context.register_drop_handler.call_args[0][0]
        self.assertFalse(handle_drop("molecule.xyz"))
        orca = os.path.join(self.tmp, "orca.inp")
        with open(orca, "w", encoding="utf-8") as handle:
            handle.write("! HF\n")
        self.assertFalse(handle_drop(orca))
        with mock.patch("PySide6.QtCore.QTimer.singleShot") as later:
            self.assertTrue(handle_drop(os.path.join(INPUTS, "rhf_energy.inp")))
        later.assert_called_once()

    def test_no_molecule_warns(self):
        P, context, windows = self.context(None)
        context.add_export_action.call_args[0][1]()
        QMessageBox.warning.assert_called_once()
        self.assertEqual(windows, {})

    def test_import_menu_is_registered(self):
        _, context, _ = self.context(_mol("O"))
        self.assertEqual(context.add_menu_action.call_args[0][0], "File/Import/GAMESS Input...")


if __name__ == "__main__":
    unittest.main()
