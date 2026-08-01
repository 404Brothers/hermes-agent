"""Linux desktop entry (``hermes.desktop``) install / removal.

``hermes desktop`` builds and launches the Electron app, but on Linux a
freshly-built app has no presence in the application launcher — no Hermes
in the KDE/GNOME menu, no icon, no "pin to taskbar". This module writes the
XDG desktop entry that gives it one, and ``hermes uninstall --gui`` removes
it again.

Two things have to be absolute for the entry to actually work:

  - ``Exec`` — the launcher runs with a minimal environment and no shell
    ``PATH`` customizations, so a bare ``hermes desktop`` silently fails for
    anyone whose hermes lives in ``~/.local/bin`` or a venv. We resolve the
    real binary and write its full path.
  - ``Icon`` — an unqualified icon name only resolves against an indexed icon
    theme, which we are not in. The desktop entry spec allows an absolute
    path instead, so we point straight at the app icon in the checkout. No
    copy: ``Exec`` already depends on that same tree, so a second copy would
    add bytes and an uninstall step without surviving anything ``Exec``
    wouldn't.

Cache refresh is best-effort and tool-gated: ``update-desktop-database`` for
the freedesktop menu cache, and ``kbuildsycoca6``/``kbuildsycoca5`` for
Plasma — each only when the binary exists, because most desktops don't ship
them and a missing one is not an error.

Import-light and side-effect-free at import time: the uninstaller and the
Electron main process both shell into this without paying for the full CLI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

DESKTOP_ENTRY_NAME = "hermes.desktop"


def is_supported() -> bool:
    """XDG desktop entries are a Linux/BSD thing — not macOS, not Windows."""
    return sys.platform.startswith(("linux", "freebsd", "openbsd", "netbsd"))


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw and raw.strip():
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def desktop_entry_path() -> Path:
    """Where the ``hermes.desktop`` entry lives."""
    return _xdg_data_home() / "applications" / DESKTOP_ENTRY_NAME


def icon_path(project_root: Path) -> Path:
    """The app icon shipped in the desktop workspace (also electron-builder's)."""
    return project_root / "apps" / "desktop" / "assets" / "icon.png"


def resolve_exec_command() -> str:
    """Build the absolute ``Exec=`` command line for ``hermes desktop``.

    Prefers the real ``hermes`` executable (argv[0] or PATH). When Hermes is
    being run as a module with no launcher installed, falls back to the
    current interpreter — also absolute — so the entry still works.
    """
    from hermes_cli.relaunch import resolve_hermes_bin

    bin_path = resolve_hermes_bin()
    if bin_path:
        argv = [str(Path(bin_path).resolve()), "desktop"]
    else:
        argv = [str(Path(sys.executable).resolve()), "-m", "hermes_cli.main", "desktop"]
    return " ".join(_quote_exec_arg(a) for a in argv)


def _quote_exec_arg(arg: str) -> str:
    """Quote one ``Exec`` argument per the desktop entry spec.

    Reserved characters require double quotes, and inside them a backslash
    and a double quote must be escaped with a backslash.
    """
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_desktop_entry(exec_command: str, icon: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Hermes\n"
        "GenericName=Hermes Desktop\n"
        "Comment=Launch Hermes Desktop\n"
        f"Exec={exec_command}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "StartupNotify=true\n"
        "StartupWMClass=Hermes\n"
    )


def refresh_desktop_databases(applications_dir: Path) -> "list[str]":
    """Reindex the menu caches. Each tool is optional; skip what isn't there.

    Returns the names of the tools actually run (for logging and tests).
    """
    ran: list[str] = []

    update_db = shutil.which("update-desktop-database")
    if update_db:
        if _run_quiet([update_db, str(applications_dir)]):
            ran.append("update-desktop-database")

    # Plasma 6 first, then Plasma 5. Only one of them is ever installed.
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        resolved = shutil.which(tool)
        if not resolved:
            continue
        if _run_quiet([resolved, "--noincremental"]):
            ran.append(tool)
        break

    return ran


def _run_quiet(cmd: "list[str]") -> bool:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def install_desktop_entry(project_root: Path) -> Optional[Path]:
    """Write (or refresh) the Hermes desktop entry. Returns its path.

    Returns ``None`` on a non-Linux platform or when the entry could not be
    written — this is a convenience, never a reason to fail a launch.
    """
    if not is_supported():
        return None

    entry_path = desktop_entry_path()
    icon = icon_path(project_root)
    # Fall back to the themed name when the checkout has no icon (a lite/
    # packaged install) — a broken absolute path renders as no icon at all.
    icon_value = str(icon) if icon.is_file() else "hermes"
    contents = render_desktop_entry(resolve_exec_command(), icon_value)

    try:
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        # Skip the rewrite when nothing changed, so a launch doesn't churn the
        # menu caches on every run.
        if entry_path.is_file() and entry_path.read_text(encoding="utf-8") == contents:
            return entry_path
        entry_path.write_text(contents, encoding="utf-8")
        # Some launchers (and older Plasma) still expect the entry to be
        # executable before they'll offer it.
        entry_path.chmod(0o755)
    except OSError:
        return None

    refresh_desktop_databases(entry_path.parent)
    return entry_path
