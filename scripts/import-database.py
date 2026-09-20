#!/usr/bin/env python3
"""Import a CSV export into a fresh, migrated database."""

from vogelvrij.db_csv import main_import

if __name__ == "__main__":
    main_import()
