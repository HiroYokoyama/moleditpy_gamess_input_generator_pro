"""Conservative input recovery; the complete source remains authoritative."""

import logging
import math
import os
import re
import stat
import tempfile

from .group_builder import (
    ELEMENTS,
    coordinate_factors,
    format_groups,
    get_option,
    parse_groups,
    set_option,
    split_groups,
)

MAX_INPUT_BYTES = 16 * 1024 * 1024
logger = logging.getLogger(__name__)


def write_input(path, text):
    """Replace an input only after its complete UTF-8 text is staged."""
    path = os.path.realpath(path)
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(path),
            prefix=".moleditpy-input-",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(text)
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def read_input(path):
    with open(path, "rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 16 MB limit.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig")
    if "\0" in text:
        raise ValueError("The input appears to be binary.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _number(value):
    value = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("Coordinates must be finite.")
    return value


def internal_rows(lines, variables="", angle_factor=1.0):
    """Display ordinary Z-matrices without evaluating input as Python code."""
    values = {}
    for line in variables.splitlines():
        match = re.fullmatch(r"\s*([A-Za-z]\w*)\s*(?:=|\s)\s*([-+\d.eEdD]+)\s*", line)
        if match:
            values[match[1].lower()] = _number(match[2])

    def value(token):
        try:
            return _number(token)
        except ValueError:
            sign = -1 if token.startswith("-") else 1
            key = token.lstrip("+-").lower()
            if key not in values:
                raise ValueError(
                    "Unresolved internal-coordinate variable: " + token
                ) from None
            return sign * values[key]

    def subtract(a, b):
        return tuple(x - y for x, y in zip(a, b))

    def cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def unit(vector):
        length = math.sqrt(sum(component * component for component in vector))
        if length < 1e-10:
            raise ValueError("Degenerate internal-coordinate reference plane.")
        return tuple(component / length for component in vector)

    rows, labels = [], {}
    for line in lines:
        parts = line.split("#", 1)[0].replace(",", " ").split()
        if not parts:
            continue
        index = len(rows)
        label = parts[0]
        symbol = re.sub(r"(?<=[A-Za-z])\d+$", "", label)
        if len(parts) != 1 + min(index, 3) * 2:
            raise ValueError("Unsupported Z-matrix row.")
        if index == 0:
            point = (0.0, 0.0, 0.0)
        else:
            refs = []
            for token in parts[1::2]:
                reference = (
                    int(token) - 1 if token.isdecimal() else labels.get(token, -1)
                )
                if reference < 0 or reference >= index or reference in refs:
                    raise ValueError("Invalid Z-matrix reference.")
                refs.append(reference)
            distance = value(parts[2])
            if distance < 0:
                raise ValueError("Negative bond distance.")
            origin = rows[refs[0]][1:]
            if index == 1:
                direction = (0.0, 0.0, 1.0)
            else:
                axis = unit(subtract(rows[refs[1]][1:], origin))
                if index == 2:
                    trial = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
                    normal = unit(cross(axis, trial))
                else:
                    normal = unit(
                        cross(axis, subtract(rows[refs[2]][1:], rows[refs[1]][1:]))
                    )
                tangent = cross(normal, axis)
                angle = math.radians(value(parts[4]) * angle_factor)
                dihedral = (
                    math.radians(value(parts[6]) * angle_factor) if index > 2 else 0.0
                )
                direction = tuple(
                    math.cos(angle) * a
                    + math.sin(angle)
                    * (math.cos(dihedral) * t - math.sin(dihedral) * n)
                    for a, t, n in zip(axis, tangent, normal)
                )
            point = tuple(o + distance * d for o, d in zip(origin, direction))
        labels[label] = index
        rows.append((symbol, *point))
    return rows


def _atom_row(parts, length):
    """(label, x, y, z) from `name ZNUC x y z`, or None for anything else."""
    if len(parts) != 5:
        return None
    try:
        znuc, *xyz = (_number(value) for value in parts[1:])
    except ValueError:
        return None
    number = int(abs(znuc))
    if number == 0 or number > len(ELEMENTS):
        label = "X"
    else:
        label = ELEMENTS[number - 1] + (":" if znuc < 0 else "")
    return (label, *(value / length for value in xyz))


def _structure_rows(body, groups, notes):
    """Atoms of a $DATA body, or [] with a note when they cannot be drawn."""
    lines = body.strip("\n").splitlines()[1:]  # the title card
    symmetry = lines[0].split() if lines else []
    if not symmetry or symmetry[0].upper() != "C1":
        notes.append(
            "Only the symmetry-unique atoms are listed, so no structure is drawn."
        )
        return []
    coord = str(get_option(groups, "CONTRL", "COORD", "UNIQUE")).upper()
    length, angle = coordinate_factors(groups)
    if coord in ("UNIQUE", "CART"):
        rows = [_atom_row(line.split(), length) for line in lines[1:]]
        return [row for row in rows if row]  # inline basis cards are not atoms
    if coord == "ZMT":
        text = "\n".join(lines[1:]).strip("\n")
        cards, _, variables = text.partition("\n\n")
        rows = internal_rows(cards.splitlines(), variables, 1.0 / angle)
        return [(row[0], *(value / length for value in row[1:])) for row in rows]
    notes.append(f"COORD={coord} is kept as text; no structure is drawn.")
    return []


def parse_input(text, source_path=""):
    """(settings, rows, notes) of a GAMESS input; ValueError when it is not one."""
    blocks = split_groups(text)
    if not any(name in ("CONTRL", "DATA") for name, _, _ in blocks):
        raise ValueError(
            f"{os.path.basename(source_path) or 'This text'} has no $CONTRL or "
            "$DATA group, so it is not a GAMESS input."
        )
    notes, options, extra, data = [], [], [], None
    for name, body, raw in blocks:
        if name == "DATA":
            data = body
            continue
        try:
            options.extend(parse_groups(raw))
        except ValueError:
            extra.append(raw.strip("\n"))

    settings = {"coord_format": "Cartesian (XYZ)"}
    for name, key, target in (
        ("CONTRL", "ICHARG", "charge"),
        ("CONTRL", "MULT", "mult"),
        ("SYSTEM", "MWORDS", "mwords"),
        ("SYSTEM", "MEMDDI", "memddi"),
    ):
        value = get_option(options, name, key)
        if value is not None:
            try:
                settings[target] = int(value)
            except ValueError:
                notes.append(f"{key}={value} is not a whole number.")
    settings.setdefault("charge", 0)
    settings.setdefault("mult", 1)
    settings.setdefault("memddi", 0)

    rows = []
    if data is None:
        notes.append("There is no $DATA group, so no structure is drawn.")
    else:
        title = data.strip("\n").splitlines()
        settings["title"] = title[0].strip() if title else ""
        try:
            rows = _structure_rows(data, options, notes)
        except ValueError as exc:
            notes.append(f"Structure could not be read: {exc}")
    if str(get_option(options, "CONTRL", "COORD", "")).upper() == "ZMT":
        has_variables = bool(data and "\n\n" in data.strip("\n"))
        settings["coord_format"] = (
            "Z-Matrix (variables)" if has_variables else "Z-Matrix"
        )

    kept = options
    for name, key in (
        ("CONTRL", "ICHARG"),
        ("CONTRL", "MULT"),
        ("CONTRL", "COORD"),
        ("SYSTEM", "MWORDS"),
        ("SYSTEM", "MEMDDI"),
    ):
        kept = set_option(kept, name, key, None)
    settings["groups"] = format_groups(kept) + "\n"
    settings["extra"] = "\n".join(extra) + "\n" if extra else ""
    return settings, rows, notes


def molecule_from_rows(rows, charge=0):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds

    mol = Chem.RWMol()
    conf = Chem.Conformer(len(rows))
    table = Chem.GetPeriodicTable()
    for index, (label, x, y, z) in enumerate(rows):
        symbol = re.sub(r"(?i)(:|-Bq)$", "", label)
        if symbol.isdecimal():
            atomic_number = int(symbol)
            if not 0 <= atomic_number <= 118:
                raise ValueError(
                    "Unknown atomic number in the molecular specification."
                )
            symbol = table.GetElementSymbol(atomic_number)
        symbol = symbol.title()
        atom = Chem.Atom(0 if symbol in ("X", "Bq") else symbol)
        atom.SetNoImplicit(True)
        if label.endswith(":") or label.lower().endswith("-bq"):
            atom.SetProp("xyz_original_symbol", label)
            atom.SetProp("custom_symbol", label)
        elif symbol in ("X", "Bq"):
            atom.SetProp("custom_symbol", symbol)
        mol.AddAtom(atom)
        conf.SetAtomPosition(index, (x, y, z))
    mol.AddConformer(conf)
    mol = mol.GetMol()
    try:
        rdDetermineBonds.DetermineConnectivity(mol)
    except (RuntimeError, ValueError):
        pass  # Coordinates are still useful when bonding cannot be inferred.
    mol.SetIntProp("_xyz_charge", charge)
    mol.UpdatePropertyCache(strict=False)
    return mol


class InputLoadingMixin:
    def detach_project(self):
        """Keep unsaved input without linking it to the host's next document."""
        self.persistent_settings = dict(self.persistent_settings or {})
        self.mark_modified = None
        self.get_molecule = None
        self.display_molecule = None
        self._project_detached = True
        self.input_notice.setText(
            "This input belongs to the previous project. Save it separately; "
            "it is no longer linked to the current project."
        )
        self.input_notice.show()
        self._update_title()

    @staticmethod
    def _restore_spin_value(widget, value, *, signed=False):
        # Project JSON may contain old, malformed or unusually large values.
        if type(value) is not int or not -(2**31) <= value < 2**31:
            return
        if not signed and value < 1:
            return
        widget.setMinimum(min(widget.minimum(), value))
        widget.setMaximum(max(widget.maximum(), value))
        widget.setValue(value)

    def _remember_generated_reference(self, key, value):
        if (
            self.persistent_settings is None
            or self.persistent_settings.get(key) == value
        ):
            return
        self.persistent_settings[key] = value
        if self.mark_modified is not None:
            try:
                self.mark_modified()
            except (RuntimeError, ValueError, AttributeError):
                logger.exception(
                    "Could not mark the project modified after input export"
                )

    def _store_generated_charge_mult(self):
        if self.persistent_settings is None:
            return
        signature = getattr(self, "_charge_signature", None)
        if signature is None:
            self.persistent_settings.pop("generated_charge_mult", None)
            return
        self.persistent_settings["generated_charge_mult"] = {
            "signature": [list(atom) for atom in signature],
            "charge": self.charge_spin.value(),
            "mult": self.mult_spin.value(),
        }

    def _restore_generated_charge_mult(self, saved):
        if not isinstance(saved, dict):
            return
        signature = getattr(self, "_charge_signature", None)
        if signature is None or saved.get("signature") != [list(a) for a in signature]:
            return
        for name, key in (("charge_spin", "charge"), ("mult_spin", "mult")):
            self._restore_spin_value(
                getattr(self, name), saved.get(key), signed=key == "charge"
            )

    def _input_text_edited(self):
        if not getattr(self, "ui_ready", False):
            return
        text = self.preview_text.toPlainText()
        override = text != getattr(self, "_generated_text", "") or getattr(
            self, "_input_text_required", False
        )
        self._text_override = override
        if self.persistent_settings is not None:
            if override:
                self.persistent_settings["input_text"] = text
            else:
                self.persistent_settings.pop("input_text", None)
        self.input_settings_widget.setEnabled(not override)
        self.input_notice.setVisible(override)
        self._current_content = text
        self._update_title()
        if self.mark_modified is not None:
            try:
                self.mark_modified()
            except (RuntimeError, ValueError, AttributeError):
                logger.exception(
                    "Could not mark the project modified after input editing"
                )

    def _write_generated_preview(self, text):
        from PySide6.QtCore import QSignalBlocker

        self._generated_text = text
        self._text_override = False
        self._input_text_required = False
        with QSignalBlocker(self.preview_text):
            self.preview_text.setPlainText(text)
        self.input_settings_widget.setEnabled(True)
        self.input_notice.hide()
        if self.persistent_settings is not None:
            self.persistent_settings.pop("input_text", None)

    def refresh_input_preview(self):
        self._text_override = False
        self._input_text_required = False
        self.input_settings_widget.setEnabled(True)
        self.input_notice.setText(
            "Full input text is authoritative. Edit Preview directly; Reset/Refresh regenerates from settings."
        )
        self.input_notice.hide()
        self.update_preview()

    def recover_input_conditions(self):
        from PySide6.QtWidgets import QMessageBox

        text = self.preview_text.toPlainText()
        try:
            parsed = parse_input(text, self.current_inp_file or "")
        except ValueError as exc:
            QMessageBox.warning(self, "Recover Conditions", str(exc))
            return
        self.restore_input_text(text, parsed)

    def load_input_file(self, path=None):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not isinstance(path, str) or not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Input File", "", "GAMESS input (*.inp);;All files (*)"
            )
        if not path:
            return False
        try:
            text = read_input(path)
            parsed = parse_input(text, path)
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, "Load Input File", str(exc))
            return False
        if not self._confirm_discard():
            return False
        if self.current_inp_file is None and getattr(self, "_text_override", False):
            reply = QMessageBox.question(
                self,
                "Replace Input Text",
                "Replace the current input text with this file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        self.restore_input_text(text, parsed, path)
        self.current_inp_file = os.path.abspath(path)
        self.filename = path
        self._saved_inp_content = self.preview_text.toPlainText()
        self._update_title()
        return True

    def restore_input_text(self, text, parsed=None, path="", *, restore_structure=True):
        from PySide6.QtCore import QSignalBlocker

        if parsed is None:
            try:
                parsed = parse_input(text, path)
            except ValueError:
                parsed = (
                    {},
                    [],
                    [
                        "Unfinished input restored verbatim. Use Preview to continue editing."
                    ],
                )
        settings, rows, notes = parsed
        self._close_builder()
        self._input_text_required = False
        self.ui_ready = False
        try:
            if rows and (restore_structure or self.mol is None):
                try:
                    mol = molecule_from_rows(rows, settings.get("charge", 0))
                    if restore_structure and self.display_molecule is not None:
                        self.display_molecule(mol)
                    self.mol = mol
                    from .main_dialog import _charge_signature

                    self._charge_signature = _charge_signature(mol)
                except (RuntimeError, ValueError, OverflowError) as exc:
                    notes.append(f"Structure could not be displayed: {exc}")
            if self.mol is not None:
                from .main_dialog import Chem

                # Even if source text matches generated text, its charge/spin
                # may differ from what the project molecule would regenerate.
                self._input_text_required = settings.get(
                    "charge", 0
                ) != Chem.GetFormalCharge(self.mol) or settings.get(
                    "mult", 1
                ) != 1 + sum(
                    atom.GetNumRadicalElectrons() for atom in self.mol.GetAtoms()
                )
            target = self.persistent_settings
            self.persistent_settings = dict(settings)
            try:
                self.load_persistent_settings()
            finally:
                self.persistent_settings = target
            if target is not None:
                target.update(
                    {
                        key: value
                        for key, value in settings.items()
                        if key not in ("charge", "mult")
                    }
                )
            for name, key in (("charge_spin", "charge"), ("mult_spin", "mult")):
                if key in settings:
                    widget = getattr(self, name)
                    self._restore_spin_value(
                        widget, settings[key], signed=key == "charge"
                    )
            self._generated_text = self.generate_input_content()
            with QSignalBlocker(self.preview_text):
                self.preview_text.setPlainText(text)
            self.input_notice.setText(
                "Full input text is authoritative. Edit Preview directly; Reset/Refresh regenerates from settings."
                + ("\n" + "\n".join(notes) if notes else "")
            )
        finally:
            self.ui_ready = True
        self._input_text_edited()
