"""Add priority column to session_tags table.

This migration adds the `priority` column to the `session_tags` table,
enabling tag stacking with explicit priority ordering. Existing rows
are assigned `priority = 0` (highest priority).

Usage:
    python scripts/add_session_tags_priority.py [--db PATH]

The script is idempotent — running it twice on the same database is safe.
"""

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    """Run the migration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".local/share/bearings-v1/sessions.db",
        help="Path to the Bearings v1 SQLite database",
    )
    args = parser.parse_args()

    db_path = args.db
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Check if priority column already exists
        cursor.execute("PRAGMA table_info(session_tags)")
        columns = {row[1] for row in cursor.fetchall()}

        if "priority" in columns:
            print("priority column already exists in session_tags. No action taken.")
            return

        # Add the priority column
        cursor.execute("ALTER TABLE session_tags ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        print("Successfully added priority column to session_tags table.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
