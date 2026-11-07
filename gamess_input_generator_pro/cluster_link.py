"""Optional handoff to the Job Manager plugin.

If the user has Job Manager installed, the input we just wrote can be sent
straight to a cluster. If they do not, nothing about this plugin should change:
the button is not shown at all, no import is attempted, no error is logged.

Job Manager is found through the host's plugin list rather than imported, since
plugins are not importable by name from each other, and it is identified by the
public ``submit_file`` entry point it documents -- a plugin that merely shares
the name but predates that API is correctly treated as absent.
"""

import logging
import os

JOB_MANAGER_PLUGIN_NAME = "Job Manager"


def find_job_manager(main_window):
    """Return the Job Manager module, or None when it is not available."""
    manager = getattr(main_window, "plugin_manager", None)
    for record in getattr(manager, "plugins", None) or []:
        try:
            if record.get("name") != JOB_MANAGER_PLUGIN_NAME:
                continue
            module = record.get("module")
        except AttributeError:
            continue
        if module is not None and callable(getattr(module, "submit_file", None)):
            return module
    return None


def is_available(main_window) -> bool:
    return find_job_manager(main_window) is not None


def submit_to_cluster(main_window, path, name="") -> bool:
    """Hand ``path`` to Job Manager's submit wizard. False if it declined."""
    module = find_job_manager(main_window)
    if module is None or not path or not os.path.isfile(path):
        return False
    try:
        return bool(module.submit_file(path, name=name or ""))
    except Exception:
        logging.warning("Could not hand the input to Job Manager", exc_info=True)
        return False
