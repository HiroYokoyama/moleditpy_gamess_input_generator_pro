"""Builds the option groups from choices; any keyword it has no control for is kept."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .constants import BUILDER_TABS, ESP_FIELDS, LEAVE_OUT
from .group_builder import (
    apply_fields,
    format_groups,
    get_option,
    needs_spherical,
    normalize_for_builder,
    parse_groups,
    set_option,
)
from .wheel_guard import install_wheel_guard

TRUE_VALUES = (".TRUE.", ".T.", "TRUE", "T")


class GamessGroupBuilderDialog(QDialog):
    def __init__(self, parent=None, groups_text=""):
        super().__init__(parent)
        self.setWindowTitle("GAMESS Group Builder")
        self.resize(560, 520)
        self.widgets = {}
        self._groups = []
        self._setup_ui()
        self.load_groups(groups_text)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for tab_name, fields in BUILDER_TABS.items():
            page = QWidget()
            form = QFormLayout(page)
            for label, group, key, kind, choices in fields:
                self._add_field(form, label, group, key, kind, choices)
            if tab_name == "Properties":
                self.esp_check = QCheckBox(
                    "Fitted charges: $ELPOT IEPOT=1 WHERE=PDC OUTPUT=BOTH, "
                    "$PDC PTSEL=CHELPG CONSTR=CHARGE"
                )
                self.esp_check.toggled.connect(self.refresh_preview)
                form.addRow(self.esp_check)
            self.tabs.addTab(page, tab_name)
        install_wheel_guard(self.tabs)
        layout.addWidget(self.tabs)
        layout.addWidget(QLabel("Groups:"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(120)
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        apply_button = QPushButton("Apply")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def _add_field(self, form, label, group, key, kind, choices):
        if kind in ("check", "value"):
            widget = QCheckBox(label)
            widget.toggled.connect(self.refresh_preview)
            form.addRow(widget)
        else:
            widget = QComboBox()
            widget.addItem(LEAVE_OUT, "")
            if kind == "map":
                for text, value in choices.items():
                    widget.addItem(text, value)
            else:
                for value in choices:
                    widget.addItem(value, value)
            widget.currentIndexChanged.connect(self.refresh_preview)
            form.addRow(label, widget)
        self.widgets[(group, key)] = (widget, kind, choices)

    def load_groups(self, text):
        """Show text in the controls; a ValueError leaves them as they were."""
        groups = parse_groups(text)
        self._groups = groups
        for (group, key), (widget, kind, choices) in self.widgets.items():
            value = get_option(groups, group, key)
            widget.blockSignals(True)
            if kind == "check":
                widget.setChecked(str(value).upper() in TRUE_VALUES)
            elif kind == "value":
                widget.setChecked(value == choices)
            else:
                index = widget.findData(value if value is not None else "")
                if index < 0:
                    widget.addItem(value, value)
                    index = widget.count() - 1
                widget.setCurrentIndex(index)
            widget.blockSignals(False)
        self.esp_check.blockSignals(True)
        self.esp_check.setChecked(
            all(get_option(groups, g, k) == v for (g, k), v in ESP_FIELDS.items())
        )
        self.esp_check.blockSignals(False)
        self.refresh_preview()

    def _field_values(self):
        values = {}
        for field, (widget, kind, choices) in self.widgets.items():
            if kind == "check":
                values[field] = ".TRUE." if widget.isChecked() else ""
            elif kind == "value":
                values[field] = choices if widget.isChecked() else ""
            else:
                values[field] = widget.currentData()
        for field, value in ESP_FIELDS.items():
            values[field] = value if self.esp_check.isChecked() else ""
        return values

    def get_groups(self):
        """The option groups as text, with what the chosen settings require."""
        before = get_option(self._groups, "BASIS", "GBASIS")
        groups = apply_fields(self._groups, self._field_values())
        after = get_option(groups, "BASIS", "GBASIS")
        if needs_spherical(before) and not needs_spherical(after):
            groups = set_option(groups, "CONTRL", "ISPHER", None)
        return format_groups(normalize_for_builder(groups)) + "\n"

    def refresh_preview(self):
        self.preview.setPlainText(self.get_groups())
