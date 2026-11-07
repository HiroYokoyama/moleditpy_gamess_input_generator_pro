import logging
import os

from .constants import DEFAULT_GROUPS, DEFAULT_TITLE

PLUGIN_NAME = "GAMESS Input Generator Pro"
PLUGIN_VERSION = "0.1.0"
PLUGIN_AUTHOR = "HiroYokoyama"
PLUGIN_LICENSE = "LGPL-3.0-or-later"
PLUGIN_DESCRIPTION = (
    "UNDER DEVELOPMENT: GAMESS (US) input generator with a group builder, "
    "live preview, presets and input loading."
)
PLUGIN_CATEGORY = "Export"
PLUGIN_TAGS = ["File", "Generator"]
PLUGIN_DEPENDENCIES = []  # PySide6/RDKit come from the host app
PLUGIN_SUPPORTED_MOLEDITPY_VERSION = ">=5.0.0, <6.0.0"
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def get_default_settings():
    return {
        "mwords": 100,
        "memddi": 0,
        "groups": DEFAULT_GROUPS,
        "title": DEFAULT_TITLE,
        "extra": "",
        "coord_format": "Cartesian (XYZ)",
    }


current_settings = get_default_settings()
_dialog_opened = False  # Guard: don't write to project file until dialog is used
_context = None  # Stored from initialize() so run() can use the context API


def run(mw, input_file=None):
    global _dialog_opened
    from PySide6.QtWidgets import QMessageBox

    # Prefer the stable context API over direct mw access
    if _context is not None:
        mw = _context.get_main_window()

    from .main_dialog import GamessSetupDialogPro

    mol = None
    try:
        mol = (
            _context.current_molecule
            if _context is not None
            else getattr(mw, "current_mol", None)
        )
    except Exception as e:
        logging.warning("GAMESS plugin: could not get current molecule: %s", e)
        mol = None
    if (
        not mol
        and not input_file
        and not isinstance(current_settings.get("input_text"), str)
    ):
        QMessageBox.warning(mw, PLUGIN_NAME, "No molecule loaded.")
        return

    filename = None
    try:
        if hasattr(mw, "init_manager"):
            filename = getattr(mw.init_manager, "current_file_path", None)
    except Exception as e:
        logging.warning("GAMESS plugin: could not get file path: %s", e)
    if not filename and mw is not None:
        title = mw.windowTitle()
        filename = title.split(" - ")[0].strip() if " - " in title else title.strip()

    if _context is not None:
        dlg = _context.get_window("dialog")
        if (
            dlg is not None
            and dlg.isVisible()
            and getattr(dlg, "_project_detached", False) is not True
        ):
            loaded = True
            if input_file:
                loaded = dlg.load_input_file(input_file)
            dlg.raise_()
            dlg.activateWindow()
            return loaded

    _dialog_opened = True

    def _mark_modified():
        if _context is not None:
            _context.mark_project_modified()

    def _get_molecule():
        if _context is not None:
            return _context.current_molecule
        return getattr(mw, "current_mol", None)

    def _display_molecule(loaded):
        if _context is not None:
            _context.current_molecule = loaded
            _context.enter_3d_viewer_mode()
            _context.set_3d_features_enabled(True)
            _context.reset_3d_camera()
            _context.mark_project_modified()

    dlg = GamessSetupDialogPro(
        parent=mw,
        mol=mol,
        filename=filename,
        persistent_settings=current_settings,
        mark_modified=_mark_modified,
        get_molecule=_get_molecule,
        display_molecule=_display_molecule,
    )
    if _context is not None:
        _context.register_window("dialog", dlg)
    dlg.show()
    if input_file:
        return dlg.load_input_file(input_file)
    return True


def initialize(context):
    global _context
    _context = context

    def show_dialog():
        mw = context.get_main_window()
        run(mw)

    context.add_export_action("GAMESS Input...", show_dialog)

    def load_input():
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            context.get_main_window(),
            "Load GAMESS Input",
            "",
            "GAMESS input (*.inp);;All files (*)",
        )
        if path:
            run(context.get_main_window(), input_file=path)

    add_menu_action = getattr(context, "add_menu_action", None)
    if callable(add_menu_action):
        add_menu_action("File/Import/GAMESS Input...", load_input)

    def validate_input(path):
        from .input_loading import parse_input, read_input

        parse_input(read_input(path), path)

    def open_input(path):
        # .inp is also ORCA's: raising hands a foreign file on to the next opener.
        validate_input(path)
        if not run(context.get_main_window(), input_file=path):
            raise RuntimeError("Input loading was cancelled or failed.")

    register_opener = getattr(context, "register_file_opener", None)
    if callable(register_opener):
        register_opener(".inp", open_input, priority=110)

    def handle_drop(path):
        if os.path.splitext(path)[1].lower() != ".inp":
            return False
        try:
            validate_input(path)
        except (OSError, ValueError, UnicodeError):
            return False

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        def load_dropped_input():
            try:
                if run(context.get_main_window(), input_file=path):
                    context.set_current_file(path)
            except Exception:
                logging.exception("Could not load dropped GAMESS input")
                QMessageBox.warning(
                    context.get_main_window(), PLUGIN_NAME, "Could not load input file."
                )

        # Leave the native drop event before opening dialogs or drawing molecules.
        QTimer.singleShot(0, context.get_main_window(), load_dropped_input)
        return True

    register_drop = getattr(context, "register_drop_handler", None)
    if callable(register_drop):
        register_drop(handle_drop, priority=110)

    # Register Persistence Handlers
    def on_save():
        # Don't write anything to the project file until the user has
        # actually opened the dialog at least once in this session.
        if not _dialog_opened:
            return None
        return current_settings

    _MOLECULE_KEYS = {"charge", "mult"}

    def on_load(data):
        if isinstance(data, dict) and data:
            # Strip molecule-specific keys that may exist in older project files
            filtered = {k: v for k, v in data.items() if k not in _MOLECULE_KEYS}
            current_settings.update(filtered)
            global _dialog_opened
            _dialog_opened = True

    def on_reset():
        global _dialog_opened
        dlg = context.get_window("dialog")
        if dlg is not None:
            try:
                dlg.close()
            except Exception as e:
                logging.warning("GAMESS plugin: could not close dialog on reset: %s", e)
            else:
                if dlg.isVisible():
                    # The host has already reset the document; this notification
                    # cannot veto it. Keep unsaved input in an independent editor.
                    dlg.detach_project()

        _dialog_opened = False
        current_settings.clear()
        current_settings.update(get_default_settings())

    context.register_save_handler(on_save)
    context.register_load_handler(on_load)
    context.register_document_reset_handler(on_reset)
