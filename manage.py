#!/usr/bin/env python
"""Django's command-line entry point for the Shiftly CRM project."""

# Importing os lets us set Django's settings module before any Django command runs.
import os
# Importing sys gives Django access to command-line arguments such as `runserver`.
import sys


def main() -> None:
    """Run a Django management command with this project's settings."""
    # This value tells Django where the central configuration file lives.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    # Delay the Django import so this script can show a useful error if it is absent.
    try:
        from django.core.management import execute_from_command_line
    except ImportError as error:
        raise ImportError(
            "Django is not installed. Create a virtual environment and run "
            "`pip install -r requirements.txt`."
        ) from error

    # Pass through every command entered by the developer, e.g. `python manage.py runserver`.
    execute_from_command_line(sys.argv)


# This condition keeps `main` from running if another module imports this file.
if __name__ == "__main__":
    main()
