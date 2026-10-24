#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


from pathlib import Path


def main():
    """Run administrative tasks."""
    base_dir = Path(__file__).resolve().parent
    venv_python = base_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Splicing the venv's site-packages onto whichever "python" happens to be
    # on PATH only works when that python's ABI matches the venv's - otherwise
    # compiled extensions (e.g. Pillow's _imaging) fail to import. Fail loudly
    # instead of silently mixing interpreters.
    if (
        venv_python.exists()
        and Path(sys.executable).resolve() != venv_python.resolve()
    ):
        sys.exit(
            f"Wrong Python interpreter: this is running under {sys.executable},\n"
            f"but the project's virtual environment is {venv_python}.\n"
            "Activate it first:\n"
            "  PowerShell:  .venv\\Scripts\\Activate.ps1\n"
            "  bash:        source .venv/Scripts/activate"
        )

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
