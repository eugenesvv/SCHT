# Contributing to SCHT

Thanks for helping improve the Star Citizen Hauling Tracker.

## Before opening an issue

- Check existing issues for the same problem or request.
- Use SCHT's current public test version, shown in the application header.
- Never upload a full `Game.log`, AppData folder, OCR failure report, or screenshot without reviewing and redacting player names, account identifiers, file paths, and unrelated desktop content.

## Development setup

SCHT targets 64-bit Windows and Python 3.12 or later.

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run the source application with `run_app.bat`. Build the standalone executable with `build_exe.bat`; build the installer with `build_installer.bat` after installing Inno Setup 6.

## Pull requests

- Keep changes focused and preserve existing tracker behavior unless the change intentionally modifies it.
- Add or update regression tests for behavior changes.
- Update the in-app help and its screenshots when visible controls or workflows change; see `docs/HELP_MANUAL_MAINTENANCE.md`.
- Run the full test suite before submitting.
- Do not commit virtual environments, build output, installers, executables, local logs, runtime AppData, or unredacted OCR material.

By contributing, you confirm that you have the right to submit your work to this project.
