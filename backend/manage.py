#!/usr/bin/env python
"""Django management entrypoint for the airfare training demo."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "airfare_demo.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Activate the venv and run "
            "`pip install -r requirements.txt`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
