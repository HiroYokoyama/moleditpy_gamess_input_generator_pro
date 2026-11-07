import json
import logging
import math
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem
from rdkit.Chem import rdMolTransforms

from . import PLUGIN_NAME, PLUGIN_VERSION, SETTINGS_FILE, cluster_link
from .constants import DEFAULT_GROUPS, DEFAULT_TITLE, EXTRA_TEMPLATES
from .group_builder import (
    ELEMENTS,
    build_input,
    cartesian_cards,
    check_input,
    coordinate_factors,
    format_groups,
    get_option,
    parse_groups,
    set_option,
    zmatrix_cards,
)
from .highlighter import GamessSyntaxHighlighter
from .input_loading import InputLoadingMixin, write_input
from .keyword_builder import GamessGroupBuilderDialog
from .wheel_guard import install_wheel_guard

# Degrees from 0/180 within which a Z-matrix reference angle is treated as
# collinear. Below that the three atoms defining the dihedral's plane are on a
# line, so the dihedral carries no information.
_ZM_LINEAR_TOL_DEG = 8.0

COORD_CARTESIAN = "Cartesian (XYZ)"
COORD_ZMATRIX = "Z-Matrix"
COORD_ZMATRIX_VARIABLES = "Z-Matrix (variables)"

_AUTO_SUFFIX = {
    "OPTIMIZE": "-opt",
    "SADPOINT": "-ts",
    "HESSIAN": "-freq",
    "RAMAN": "-raman",
    "NMR": "-nmr",
    "GRADIENT": "-grad",
}


def _zm_well_conditioned(angle_deg: float) -> bool:
    """True when *angle_deg* defines a usable Z-matrix reference plane."""
    return _ZM_LINEAR_TOL_DEG < angle_deg < 180.0 - _ZM_LINEAR_TOL_DEG


def _is_ghost_symbol(symbol: str) -> bool:
    """Bq, El-Bq (Gaussian), El: (ORCA) and X carry no electrons."""
    s = symbol.strip()
    return s.endswith(":") or s.upper() in ("BQ", "X") or s.upper().endswith("-BQ")


def _custom_symbol(atom) -> str:
    return atom.GetProp("custom_symbol").strip() if atom.HasProp("custom_symbol") else ""


def _atom_card(atom):
    """(label, ZNUC) for a $DATA card: a ghost keeps its element's basis and no charge."""
    custom = _custom_symbol(atom)
    if not _is_ghost_symbol(custom):
        return atom.GetSymbol(), float(atom.GetAtomicNum())
    element = re.sub(r"(?i)(:|-bq)$", "", custom).title()
    if element in ELEMENTS:
        return element, -float(ELEMENTS.index(element) + 1)
    return "BQ", 0.0


def _electron_count(mol, charge: int) -> int:
    """Electrons of the neutral-minus-charge system, ghosts excluded."""
    protons = sum(
        atom.GetAtomicNum()
        for atom in mol.GetAtoms()
        if not _is_ghost_symbol(_custom_symbol(atom))
    )
    return protons - charge


def _charge_signature(mol):
    """What calc_initial_charge_mult reads; a change means recompute."""
    return tuple(
        (
            a.GetAtomicNum(),
            a.GetFormalCharge(),
            a.GetNumRadicalElectrons(),
            _custom_symbol(a),
        )
        for a in mol.GetAtoms()
    )


class GamessSetupDialogPro(QDialog, InputLoadingMixin):
    """GAMESS Input Generator Pro."""

    def __init__(
        self,
        parent=None,
        mol=None,
        filename=None,
        persistent_settings=None,
        mark_modified=None,
        get_molecule=None,
        display_molecule=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"{PLUGIN_NAME} v{PLUGIN_VERSION}")
        self.resize(1100, 800)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setSizeGripEnabled(True)
        self.mol = mol
        self.filename = filename
        self.persistent_settings = persistent_settings
        self.mark_modified = mark_modified
        self.get_molecule = get_molecule
        self.display_molecule = display_molecule
        saved_text = (persistent_settings or {}).get("input_text")
        saved_charge_mult = (persistent_settings or {}).get("generated_charge_mult")
        self._text_override = False
        self.current_inp_file = None  # path of the .inp file last saved/opened
        self._saved_inp_content = None  # content at last save (for dirty detection)
        self._current_content = ""  # cached output of the most recent generate
        self._generation_error = None
        self.builder_dialog = None
        self.ui_ready = False
        self.setup_ui()
        ctrl_s = QShortcut(QKeySequence.StandardKey.Save, self)
        ctrl_s.activated.connect(self._on_ctrl_s)
        self.load_presets_from_file()
        self.load_persistent_settings()
        self.calc_initial_charge_mult()
        self._restore_generated_charge_mult(saved_charge_mult)
        self.ui_ready = True
        if isinstance(saved_text, str):
            self.restore_input_text(saved_text, restore_structure=False)
        else:
            self.update_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def setup_ui(self):
        main_layout = QVBoxLayout()
        file_actions = QHBoxLayout()
        file_actions.addStretch()
        self.load_btn = QPushButton("Load Input File...")
        self.load_btn.clicked.connect(self.load_input_file)
        file_actions.addWidget(self.load_btn)
        main_layout.addLayout(file_actions)

        content_layout = QHBoxLayout()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        settings_container = QWidget()
        self.input_settings_widget = settings_container
        settings_layout = QVBoxLayout(settings_container)

        preset_group = QGroupBox("Preset Management")
        preset_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self.apply_selected_preset)
        preset_layout.addWidget(QLabel("Preset:"))
        preset_layout.addWidget(self.preset_combo, 1)
        self.btn_save_preset = QPushButton("Save New...")
        self.btn_save_preset.clicked.connect(self.save_preset_dialog)
        preset_layout.addWidget(self.btn_save_preset)
        self.btn_del_preset = QPushButton("Delete")
        self.btn_del_preset.clicked.connect(self.delete_preset)
        preset_layout.addWidget(self.btn_del_preset)
        preset_group.setLayout(preset_layout)
        settings_layout.addWidget(preset_group)

        title_group = QGroupBox("Title (first 80 columns)")
        title_layout = QVBoxLayout()
        self.comment_edit = QLineEdit(DEFAULT_TITLE)
        self.comment_edit.textChanged.connect(self.update_preview)
        title_layout.addWidget(self.comment_edit)
        title_group.setLayout(title_layout)
        settings_layout.addWidget(title_group)

        system_group = QGroupBox("Memory per process ($SYSTEM)")
        system_layout = QFormLayout()
        self.mwords_spin = QSpinBox()
        self.mwords_spin.setRange(1, 999999)
        self.mwords_spin.setValue(100)
        self.mwords_spin.valueChanged.connect(self._memory_changed)
        self.mwords_hint = QLabel()
        mwords_row = QHBoxLayout()
        mwords_row.addWidget(self.mwords_spin)
        mwords_row.addWidget(self.mwords_hint)
        system_layout.addRow("Replicated (MWORDS):", mwords_row)
        self.memddi_spin = QSpinBox()
        self.memddi_spin.setRange(0, 9999999)
        self.memddi_spin.setToolTip(
            "Distributed memory, in megawords, shared by the whole job. "
            "Coupled cluster needs it above zero."
        )
        self.memddi_spin.valueChanged.connect(self._memory_changed)
        self.memddi_hint = QLabel()
        memddi_row = QHBoxLayout()
        memddi_row.addWidget(self.memddi_spin)
        memddi_row.addWidget(self.memddi_hint)
        system_layout.addRow("Distributed (MEMDDI):", memddi_row)
        system_group.setLayout(system_layout)
        settings_layout.addWidget(system_group)

        kw_group = QGroupBox("Option Groups")
        kw_layout = QVBoxLayout()
        kw_h_layout = QHBoxLayout()
        self.keywords_edit = QTextEdit(DEFAULT_GROUPS)
        self.keywords_edit.setFont(QFont("Courier New", 9))
        self.keywords_edit.setFixedHeight(110)
        self.keywords_edit.textChanged.connect(self.update_preview)
        self.kw_highlighter = GamessSyntaxHighlighter(self.keywords_edit.document())
        self.btn_route = QPushButton("Builder...")
        self.btn_route.clicked.connect(self.open_keyword_builder)
        kw_h_layout.addWidget(self.keywords_edit)
        kw_h_layout.addWidget(self.btn_route)
        kw_layout.addLayout(kw_h_layout)
        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("color: #b35900;")
        self.warnings_label.hide()
        kw_layout.addWidget(self.warnings_label)
        kw_group.setLayout(kw_layout)
        settings_layout.addWidget(kw_group)

        mol_group = QGroupBox("Molecular Specification")
        mol_layout = QHBoxLayout()
        self.charge_spin = QSpinBox()
        self.charge_spin.setRange(-10, 10)
        self.charge_spin.valueChanged.connect(self.validate_charge_mult)
        self.mult_spin = QSpinBox()
        self.mult_spin.setRange(1, 10)
        self.mult_spin.valueChanged.connect(self._multiplicity_changed)
        mol_layout.addWidget(QLabel("Charge (ICHARG):"))
        mol_layout.addWidget(self.charge_spin)
        mol_layout.addWidget(QLabel("Mult (MULT):"))
        mol_layout.addWidget(self.mult_spin)
        self.default_palette = self.charge_spin.palette()
        mol_group.setLayout(mol_layout)
        settings_layout.addWidget(mol_group)

        coord_group = QGroupBox("Coordinate Format")
        coord_layout = QVBoxLayout()
        self.coord_format_combo = QComboBox()
        self.coord_format_combo.addItems(
            [COORD_CARTESIAN, COORD_ZMATRIX, COORD_ZMATRIX_VARIABLES]
        )
        self.coord_format_combo.currentIndexChanged.connect(self.update_preview)
        coord_layout.addWidget(self.coord_format_combo)
        self.coord_notice = QLabel()
        self.coord_notice.setWordWrap(True)
        self.coord_notice.setStyleSheet("color: #b35900;")
        self.coord_notice.hide()
        coord_layout.addWidget(self.coord_notice)
        coord_group.setLayout(coord_layout)
        settings_layout.addWidget(coord_group)

        extra_group = QGroupBox("Extra Groups (copied as written, after $DATA)")
        extra_layout = QVBoxLayout()
        extra_h = QHBoxLayout()
        self.tail_template_combo = QComboBox()
        self.tail_template_combo.addItem("Select Example Template...")
        self.tail_template_combo.addItems(list(EXTRA_TEMPLATES))
        extra_h.addWidget(self.tail_template_combo, 1)
        self.btn_insert_tail = QPushButton("Insert")
        self.btn_insert_tail.clicked.connect(self.insert_tail_template)
        extra_h.addWidget(self.btn_insert_tail)
        extra_layout.addLayout(extra_h)
        self.tail_edit = QTextEdit()
        self.tail_edit.setFont(QFont("Courier New", 9))
        self.tail_edit.setFixedHeight(100)
        self.tail_edit.setPlaceholderText("$HESS, $DIPDR, $VEC from a punch file")
        self.tail_edit.textChanged.connect(self.update_preview)
        extra_layout.addWidget(self.tail_edit)
        extra_group.setLayout(extra_layout)
        settings_layout.addWidget(extra_group)

        settings_layout.addStretch()
        scroll_area.setWidget(settings_container)
        install_wheel_guard(settings_container)
        content_layout.addWidget(scroll_area, 3)

        preview_group = QGroupBox("Input Preview")
        preview_layout = QVBoxLayout()
        self.preview_text = QTextEdit()
        self.preview_text.textChanged.connect(self._input_text_edited)
        self.preview_text.setFont(QFont("Courier New", 10))
        self.preview_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.highlighter = GamessSyntaxHighlighter(self.preview_text.document())
        preview_layout.addWidget(self.preview_text)
        self.input_notice = QLabel(
            "Full input text is authoritative. Edit Preview directly; Reset/Refresh regenerates from settings."
        )
        self.input_notice.setWordWrap(True)
        self.input_notice.hide()
        preview_layout.addWidget(self.input_notice)
        recover_btn = QPushButton("Recover Conditions from Text")
        recover_btn.clicked.connect(self.recover_input_conditions)
        preview_layout.addWidget(recover_btn)
        btn_refresh = QPushButton("Reset/Refresh Preview")
        btn_refresh.clicked.connect(self.refresh_input_preview)
        preview_layout.addWidget(btn_refresh)
        preview_group.setLayout(preview_layout)
        content_layout.addWidget(preview_group, 4)

        main_layout.addLayout(content_layout)

        cb_layout = QHBoxLayout()
        cb_layout.addStretch()
        self.auto_suffix_cb = QCheckBox("Auto Suffix")
        self.auto_suffix_cb.setChecked(True)
        self.auto_suffix_cb.stateChanged.connect(self.update_preview)
        self.auto_suffix_cb.stateChanged.connect(self.save_global_settings)
        cb_layout.addWidget(self.auto_suffix_cb)
        main_layout.addLayout(cb_layout)

        btn_layout = QHBoxLayout()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        self.btn_close.setStyleSheet("padding: 8px; font-size: 14px;")
        self.btn_close.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self.save_btn = QPushButton("Save GAMESS Input File...")
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setStyleSheet("font-weight: bold; padding: 8px; font-size: 14px;")
        self.save_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self.submit_btn = QPushButton("Submit to Cluster...")
        self.submit_btn.clicked.connect(self.submit_to_cluster)
        self.submit_btn.setStyleSheet("padding: 8px; font-size: 14px;")
        self.submit_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.submit_btn.setToolTip(
            "Save the input and hand it to the Job Manager plugin, which uploads "
            "and submits it to a remote cluster."
        )
        # Only meaningful with Job Manager installed; otherwise it is not shown.
        self.submit_btn.setVisible(cluster_link.is_available(self.parent()))

        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(self.submit_btn)
        btn_layout.addWidget(self.save_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self._memory_changed()

    def _memory_changed(self):
        # One megaword is eight megabytes.
        self.mwords_hint.setText(f"= {self.mwords_spin.value() * 8 / 1000:.1f} GB")
        self.memddi_hint.setText(f"= {self.memddi_spin.value() * 8 / 1000:.1f} GB")
        self.update_preview()

    def submit_to_cluster(self):
        """Hand the saved input to Job Manager. Saves first when needed."""
        if self.current_inp_file is None or self._is_modified():
            self.save_file()
        if not self.current_inp_file or not os.path.isfile(self.current_inp_file):
            return  # the user cancelled the save dialog
        name = os.path.splitext(os.path.basename(self.current_inp_file))[0]
        if not cluster_link.submit_to_cluster(
            self.parent(), self.current_inp_file, name=name
        ):
            QMessageBox.warning(
                self,
                PLUGIN_NAME,
                "Job Manager could not accept the file. Check that the plugin is "
                "installed and enabled.",
            )
        else:
            self.accept()

    def insert_tail_template(self):
        template = EXTRA_TEMPLATES.get(self.tail_template_combo.currentText())
        if not template:
            return
        self.tail_edit.textCursor().insertText(template)
        self.tail_edit.setFocus()

    # ------------------------------------------------------------------
    # Molecule / coordinates
    # ------------------------------------------------------------------

    def _resolve_live_mol(self):
        """Prefer the currently active molecule via the context API callback."""
        try:
            if self.get_molecule is not None:
                live = self.get_molecule()
            else:
                live = getattr(self.parent(), "current_mol", None)
            if live is not None:
                self.mol = live
        except Exception as _e:
            logging.warning("_resolve_live_mol failed: %s", _e)
        return self.mol

    def _cartesian_atoms(self):
        conf = self.mol.GetConformer()
        atoms = []
        for atom in self.mol.GetAtoms():
            pos = conf.GetAtomPosition(atom.GetIdx())
            if not all(math.isfinite(v) for v in (pos.x, pos.y, pos.z)):
                raise ValueError("Coordinates must be finite.")
            atoms.append((*_atom_card(atom), pos.x, pos.y, pos.z))
        return atoms

    def _build_zmatrix_data(self):
        """Z-matrix rows of {"symbol", "refs" (0-based), "values"}, one per atom."""
        atoms = list(self.mol.GetAtoms())
        conf = self.mol.GetConformer()

        defined = []
        z_data = []

        for i, atom in enumerate(atoms):
            symbol = atom.GetSymbol()

            if i == 0:
                z_data.append({"symbol": symbol, "refs": [], "values": []})
                defined.append(i)
                continue

            neighbors = [n.GetIdx() for n in atom.GetNeighbors()]
            candidates = [n for n in neighbors if n in defined]
            if not candidates:
                candidates = defined[:]

            refs = [candidates[-1] if candidates else 0]

            # A reference collinear with i-ref1 leaves the dihedral below
            # undefined, so prefer a bent one when one exists.
            candidates_2 = [x for x in defined if x != refs[0]]
            if candidates_2:
                pick = candidates_2[-1]
                if not _zm_well_conditioned(
                    rdMolTransforms.GetAngleDeg(conf, i, refs[0], pick)
                ):
                    for cand in reversed(candidates_2):
                        if _zm_well_conditioned(
                            rdMolTransforms.GetAngleDeg(conf, i, refs[0], cand)
                        ):
                            pick = cand
                            break
                refs.append(pick)

            # The reference plane also degenerates when ref3 is collinear
            # with ref1-ref2.
            candidates_3 = [x for x in defined if x not in refs]
            if candidates_3:
                pick = candidates_3[-1]
                if not _zm_well_conditioned(
                    rdMolTransforms.GetAngleDeg(conf, refs[0], refs[1], pick)
                ):
                    for cand in reversed(candidates_3):
                        if _zm_well_conditioned(
                            rdMolTransforms.GetAngleDeg(conf, refs[0], refs[1], cand)
                        ):
                            pick = cand
                            break
                refs.append(pick)

            row = {"symbol": symbol, "refs": [], "values": []}
            if len(refs) >= 1:
                row["refs"].append(refs[0])
                row["values"].append(rdMolTransforms.GetBondLength(conf, i, refs[0]))
            if len(refs) >= 2:
                row["refs"].append(refs[1])
                row["values"].append(
                    rdMolTransforms.GetAngleDeg(conf, i, refs[0], refs[1])
                )
            if len(refs) >= 3:
                row["refs"].append(refs[2])
                row["values"].append(
                    rdMolTransforms.GetDihedralDeg(conf, i, refs[0], refs[1], refs[2])
                )

            if not all(math.isfinite(value) for value in row["values"]):
                raise ValueError(
                    "A linear reference plane cannot define this Z-matrix."
                )
            if len(row["values"]) >= 2 and not _zm_well_conditioned(row["values"][1]):
                raise ValueError("A linear angle cannot define this Z-matrix.")
            z_data.append(row)
            defined.append(i)

        return z_data

    def _coordinate_cards(self, groups):
        """(cards, COORD value, notice) for the selected format."""
        if not self._resolve_live_mol():
            return [], "UNIQUE", ""
        length, angle = coordinate_factors(groups)
        style = self.coord_format_combo.currentText()
        notice = ""
        if style != COORD_CARTESIAN:
            ghosts = any(
                _is_ghost_symbol(_custom_symbol(atom)) for atom in self.mol.GetAtoms()
            )
            if ghosts:
                notice = "Ghost atoms keep their basis only in Cartesian: using Cartesian."
            else:
                try:
                    rows = self._build_zmatrix_data()
                    variables = style == COORD_ZMATRIX_VARIABLES
                    return (
                        zmatrix_cards(rows, variables, length, angle),
                        "ZMT",
                        "",
                    )
                except (ValueError, RuntimeError) as exc:
                    notice = f"{exc} Using Cartesian."
        return cartesian_cards(self._cartesian_atoms(), length), "UNIQUE", notice

    # ------------------------------------------------------------------
    # Preview / generation
    # ------------------------------------------------------------------

    def _refresh_charge_mult_if_molecule_changed(self):
        """Recompute charge and mult when the live molecule is not what they described."""
        if not self._resolve_live_mol():
            return
        try:
            signature = _charge_signature(self.mol)
        except Exception as _e:
            logging.warning("charge signature failed: %s", _e)
            return
        if signature != getattr(self, "_charge_signature", None):
            self.calc_initial_charge_mult()

    def update_preview(self):
        if not getattr(self, "ui_ready", False):
            return
        if getattr(self, "_text_override", False):
            return

        self._refresh_charge_mult_if_molecule_changed()

        if self.persistent_settings is not None:
            p = self.persistent_settings
            self._store_generated_charge_mult()
            p["mwords"] = self.mwords_spin.value()
            p["memddi"] = self.memddi_spin.value()
            p["groups"] = self.keywords_edit.toPlainText()
            p["title"] = self.comment_edit.text()
            p["extra"] = self.tail_edit.toPlainText()
            p["coord_format"] = self.coord_format_combo.currentText()

        self._current_content = self.generate_input_content()
        self._write_generated_preview(self._current_content)
        self._update_title()

        if self.mark_modified is not None:
            try:
                self.mark_modified()
            except Exception as _e:
                logging.warning("mark_modified failed: %s", _e)

    def load_persistent_settings(self):
        if not self.persistent_settings:
            return
        self.blockSignals(True)
        try:
            p = self.persistent_settings
            if "mwords" in p:
                self._restore_spin_value(self.mwords_spin, p["mwords"])
            if "memddi" in p:
                self._restore_memddi(p["memddi"])
            if "groups" in p:
                self.keywords_edit.setPlainText(p["groups"])
            if "title" in p:
                self.comment_edit.setText(p["title"])
            if "extra" in p:
                self.tail_edit.setPlainText(p["extra"])
            if "coord_format" in p:
                self.coord_format_combo.setCurrentText(p["coord_format"])
        finally:
            self.blockSignals(False)

    def _restore_memddi(self, value):
        if type(value) is int and 0 <= value < 2**31:
            self.memddi_spin.setMaximum(max(self.memddi_spin.maximum(), value))
            self.memddi_spin.setValue(value)

    def generate_input_content(self):
        """The complete input text, or an ! line saying why there can be none."""
        self._generation_error = None
        notes = []
        try:
            groups = parse_groups(self.keywords_edit.toPlainText())
            cards, coord, notice = self._coordinate_cards(groups)
            if notice:
                notes.append(notice)
            content = build_input(
                self.comment_edit.text(),
                self.keywords_edit.toPlainText(),
                cards,
                self.charge_spin.value(),
                self.mult_spin.value(),
                self.mwords_spin.value(),
                self.memddi_spin.value(),
                coord,
                self.tail_edit.toPlainText(),
            )
        except (ValueError, RuntimeError) as exc:
            self._generation_error = str(exc)
            self._show_notes(self.warnings_label, [])
            return f"! Invalid input: {exc}\n"
        self._show_notes(self.coord_notice, notes)
        self._show_notes(self.warnings_label, self._warnings(groups))
        return content

    def _warnings(self, groups):
        electrons = None
        if self.mol is not None:
            electrons = _electron_count(self.mol, self.charge_spin.value())
        return check_input(
            groups,
            self.mult_spin.value(),
            electrons,
            self.memddi_spin.value(),
            self.tail_edit.toPlainText(),
        )

    @staticmethod
    def _show_notes(label, notes):
        label.setText("\n".join(notes))
        label.setVisible(bool(notes))

    # ------------------------------------------------------------------
    # Builder
    # ------------------------------------------------------------------

    def open_keyword_builder(self):
        try:
            if self.builder_dialog is None:
                self.builder_dialog = GamessGroupBuilderDialog(
                    self, self.keywords_edit.toPlainText()
                )
                self.builder_dialog.finished.connect(
                    lambda r: self.on_builder_finished(r)
                )
            else:
                self.builder_dialog.load_groups(self.keywords_edit.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Builder", f"Cannot read the groups:\n{exc}")
            return
        self.builder_dialog.show()
        self.builder_dialog.raise_()
        self.builder_dialog.activateWindow()

    def on_builder_finished(self, result):
        if result == QDialog.DialogCode.Accepted and self.builder_dialog is not None:
            self.keywords_edit.setPlainText(self.builder_dialog.get_groups())
        self.update_preview()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_file(self):
        if self._generation_error and not getattr(self, "_text_override", False):
            QMessageBox.critical(
                self, "Error", f"Cannot generate the input:\n{self._generation_error}"
            )
            return

        default_dir = os.getcwd()
        default_base = "gamess_job"

        if self.filename:
            if os.path.isabs(self.filename):
                default_dir = os.path.dirname(self.filename)
            base_name = self.filename.replace("\\", "/").split("/")[-1]
            if base_name:
                default_base = os.path.splitext(base_name)[0]

        default_base = re.sub(r'[\\/*?:"<>|]', "_", default_base).strip().lstrip("_")
        if not default_base:
            default_base = "gamess_job"

        if self.auto_suffix_cb.isChecked():
            suffix = self._auto_suffix()
            if suffix and not default_base.endswith(suffix):
                default_base += suffix

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GAMESS Input",
            os.path.join(default_dir, default_base + ".inp"),
            "GAMESS Input (*.inp);;All Files (*)",
        )

        if file_path:
            try:
                content = self.preview_text.toPlainText()
                write_input(file_path, content)
                self.current_inp_file = file_path
                self._saved_inp_content = content
                self._update_title()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{e!s}")

    def _auto_suffix(self):
        try:
            groups = parse_groups(self.keywords_edit.toPlainText())
        except ValueError:
            return ""
        runtyp = str(get_option(groups, "CONTRL", "RUNTYP", "ENERGY")).upper()
        if runtyp in _AUTO_SUFFIX:
            return _AUTO_SUFFIX[runtyp]
        if str(get_option(groups, "CONTRL", "TDDFT", "")).upper() == "EXCITE":
            return "-td"
        return "-sp"

    # ------------------------------------------------------------------
    # Preset Management
    # ------------------------------------------------------------------

    def _preset_values(self):
        return {
            "mwords": self.mwords_spin.value(),
            "memddi": self.memddi_spin.value(),
            "groups": self.keywords_edit.toPlainText(),
            "extra": self.tail_edit.toPlainText(),
            "coord_format": self.coord_format_combo.currentText(),
        }

    def load_presets_from_file(self):
        self.presets_data = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.presets_data = json.load(f)
            except (OSError, ValueError) as e:
                logging.warning("Reading presets from %s failed: %s", SETTINGS_FILE, e)

        if "Default" not in self.presets_data:
            self.presets_data["Default"] = {
                "mwords": 100,
                "memddi": 0,
                "groups": DEFAULT_GROUPS,
                "extra": "",
                "coord_format": COORD_CARTESIAN,
            }

        global_cfg = self.presets_data.get("Global", {})
        if "auto_suffix" in global_cfg:
            self.auto_suffix_cb.setChecked(global_cfg["auto_suffix"])

        self.update_preset_combo()

    def update_preset_combo(self):
        current = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(sorted(k for k in self.presets_data if k != "Global"))
        if current in self.presets_data:
            self.preset_combo.setCurrentText(current)
        elif "Default" in self.presets_data:
            self.preset_combo.setCurrentText("Default")
        self.preset_combo.blockSignals(False)
        self.apply_selected_preset()

    def apply_selected_preset(self):
        name = self.preset_combo.currentText()
        if name not in self.presets_data:
            return
        data = self.presets_data[name]
        self.mwords_spin.setValue(data.get("mwords", 100))
        self._restore_memddi(data.get("memddi", 0))
        self.keywords_edit.setPlainText(data.get("groups", DEFAULT_GROUPS))
        self.tail_edit.setPlainText(data.get("extra", ""))
        self.coord_format_combo.setCurrentText(data.get("coord_format", COORD_CARTESIAN))
        self.update_preview()

    def save_preset_dialog(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset Name:")
        if ok and name:
            self.presets_data[name] = self._preset_values()
            self.save_presets_to_file()
            self.update_preset_combo()
            self.preset_combo.setCurrentText(name)

    def delete_preset(self):
        name = self.preset_combo.currentText()
        if name == "Default":
            QMessageBox.warning(self, "Warning", "Cannot delete Default preset.")
            return
        confirm = QMessageBox.question(self, "Confirm", f"Delete preset '{name}'?")
        if confirm == QMessageBox.StandardButton.Yes:
            del self.presets_data[name]
            self.save_presets_to_file()
            self.update_preset_combo()

    def save_presets_to_file(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.presets_data, f, indent=4)
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Failed to save presets: {e}")

    def save_global_settings(self):
        if not getattr(self, "ui_ready", False):
            return
        self.presets_data.setdefault("Global", {})[
            "auto_suffix"
        ] = self.auto_suffix_cb.isChecked()
        self.save_presets_to_file()

    # ------------------------------------------------------------------
    # Charge/Mult Logic
    # ------------------------------------------------------------------

    def calc_initial_charge_mult(self):
        if not self._resolve_live_mol():
            return
        try:
            self._charge_signature = _charge_signature(self.mol)
            try:
                charge = Chem.GetFormalCharge(self.mol)
            except Exception:
                charge = 0
            num_radical = sum(
                atom.GetNumRadicalElectrons() for atom in self.mol.GetAtoms()
            )
            self.charge_spin.setValue(int(charge))
            self.mult_spin.setValue(int(num_radical + 1))
            self.validate_charge_mult()
        except Exception as _e:
            logging.warning("calc_initial_charge_mult failed: %s", _e)

    def _multiplicity_changed(self):
        # RHF with an open shell stops GAMESS at once, and it is the default SCFTYP.
        if self.mult_spin.value() > 1:
            try:
                groups = parse_groups(self.keywords_edit.toPlainText())
            except ValueError:
                groups = None
            if (
                groups is not None
                and str(get_option(groups, "CONTRL", "SCFTYP", "RHF")).upper() == "RHF"
            ):
                self.keywords_edit.setPlainText(
                    format_groups(set_option(groups, "CONTRL", "SCFTYP", "ROHF")) + "\n"
                )
        self.validate_charge_mult()

    def validate_charge_mult(self):
        if not self._resolve_live_mol():
            return
        try:
            charge = self.charge_spin.value()
            mult = self.mult_spin.value()
            total_electrons = _electron_count(self.mol, charge)
            is_valid = (
                0 <= mult - 1 <= total_electrons
                and (total_electrons - mult + 1) % 2 == 0
            )
            if is_valid:
                self.charge_spin.setPalette(self.default_palette)
                self.mult_spin.setPalette(self.default_palette)
            else:
                p = self.charge_spin.palette()
                p.setColor(QPalette.ColorRole.Base, QColor("#FFDDDD"))
                p.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.red)
                self.charge_spin.setPalette(p)
                self.mult_spin.setPalette(p)
            self.update_preview()
        except Exception as _e:
            logging.warning("validate_charge_mult failed: %s", _e)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _confirm_discard(self):
        """True when it is safe to close: saved, unchanged, or the user said so."""
        if not (self.current_inp_file and self._is_modified()):
            return True
        name = os.path.basename(self.current_inp_file)
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            f'Save changes to "{name}"?',
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            self._save_current_file()
            return not self._is_modified()  # False when the save failed
        return reply != QMessageBox.StandardButton.Cancel

    def _close_builder(self):
        if self.builder_dialog is not None:
            self.builder_dialog.close()

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        # After the question, not before: cancelling the close must leave the
        # builder window open behind the dialog.
        self._close_builder()
        # Accepted rather than delegated: QDialog's own closeEvent calls
        # reject(), which would ask the same question again.
        event.accept()

    def _is_modified(self):
        if self.current_inp_file is None or self._saved_inp_content is None:
            return False
        return self.preview_text.toPlainText() != self._saved_inp_content

    def _update_title(self):
        base = f"{PLUGIN_NAME} v{PLUGIN_VERSION}"
        if getattr(self, "_project_detached", False):
            base += " - Detached input"
        if self.current_inp_file:
            name = os.path.basename(self.current_inp_file)
            dirty = " *" if self._is_modified() else ""
            self.setWindowTitle(f"{name}{dirty} - {base}")
        else:
            self.setWindowTitle(f"{base} *")

    def _save_current_file(self):
        if not self.current_inp_file:
            return
        try:
            content = self.preview_text.toPlainText()
            write_input(self.current_inp_file, content)
            self._saved_inp_content = content
            self._current_content = content
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")

    def _on_ctrl_s(self):
        if self.current_inp_file:
            self._save_current_file()
        else:
            self.save_file()

    def accept(self):
        self._close_builder()
        super().accept()

    def reject(self):
        # Esc and the window's own Close both arrive here without a closeEvent,
        # so the unsaved-changes question has to be asked here too.
        if not self._confirm_discard():
            return
        self._close_builder()
        super().reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            focused = self.focusWidget()
            if isinstance(focused, (QLineEdit, QComboBox, QSpinBox, QTextEdit)):
                focused.clearFocus()
                return
        super().keyPressEvent(event)
