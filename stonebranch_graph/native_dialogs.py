from __future__ import annotations

from pathlib import Path
import platform
import subprocess
from shutil import which


def pick_directory(title: str, initial_dir: Path | None = None) -> Path | None:
    initial = _existing_dir(initial_dir)

    if platform.system().lower() == "windows":
        result = _windows_folder_dialog(title, initial)
        if result:
            return result

    result = _tk_directory_dialog(title, initial)
    return result


def pick_file(
    title: str,
    initial_dir: Path | None = None,
    filetypes: tuple[tuple[str, str], ...] = (("JSON files", "*.json"), ("All files", "*.*")),
) -> Path | None:
    initial = _existing_dir(initial_dir)

    if platform.system().lower() == "windows":
        result = _windows_file_dialog(title, initial, filetypes)
        if result:
            return result

    result = _tk_file_dialog(title, initial, filetypes)
    return result


def _existing_dir(path: Path | None) -> Path:
    if path is None:
        return Path.cwd()

    try:
        p = Path(path)
        if p.exists() and p.is_dir():
            return p
        if p.exists() and p.is_file():
            return p.parent

        parent = p
        while parent != parent.parent and not parent.exists():
            parent = parent.parent
        if parent.exists() and parent.is_dir():
            return parent
    except Exception:
        pass

    return Path.cwd()


def _windows_folder_dialog(title: str, initial_dir: Path) -> Path | None:
    powershell = which("powershell") or which("pwsh")
    if not powershell:
        return None

    script = f"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = {_ps_quote(title)}
$dialog.SelectedPath = {_ps_quote(str(initial_dir))}
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
  Write-Output $dialog.SelectedPath
}}
"""
    return _run_powershell_dialog(powershell, script)


def _windows_file_dialog(
    title: str,
    initial_dir: Path,
    filetypes: tuple[tuple[str, str], ...],
) -> Path | None:
    powershell = which("powershell") or which("pwsh")
    if not powershell:
        return None

    filter_parts = [f"{label} ({pattern})|{pattern}" for label, pattern in filetypes]
    filter_string = "|".join(filter_parts) or "All files (*.*)|*.*"

    script = f"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = {_ps_quote(title)}
$dialog.InitialDirectory = {_ps_quote(str(initial_dir))}
$dialog.Filter = {_ps_quote(filter_string)}
$dialog.Multiselect = $false
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
  Write-Output $dialog.FileName
}}
"""
    return _run_powershell_dialog(powershell, script)


def _run_powershell_dialog(powershell: str, script: str) -> Path | None:
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    return Path(lines[-1].strip('"'))


def _tk_directory_dialog(title: str, initial_dir: Path) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = filedialog.askdirectory(title=title, initialdir=str(initial_dir), mustexist=False)
        root.destroy()
        return Path(value) if value else None
    except Exception:
        return None


def _tk_file_dialog(
    title: str,
    initial_dir: Path,
    filetypes: tuple[tuple[str, str], ...],
) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = filedialog.askopenfilename(title=title, initialdir=str(initial_dir), filetypes=filetypes)
        root.destroy()
        return Path(value) if value else None
    except Exception:
        return None


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
