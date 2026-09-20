"""Consistent CSV export and empty-database import for public application tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from .database import database_url

SCHEMA = "public"
NULL_MARKER = r"\N"


def connect():
    url = make_url(database_url()).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False))


def tables(cursor):
    cursor.execute(
        """SELECT relation.relname
           FROM pg_class relation
           JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = %s AND relation.relkind IN ('r', 'p')
             AND NOT EXISTS (
               SELECT 1 FROM pg_depend dependency
               WHERE dependency.classid = 'pg_class'::regclass
                 AND dependency.objid = relation.oid
                 AND dependency.deptype = 'e'
             )
           ORDER BY relation.relname""",
        (SCHEMA,),
    )
    return [row[0] for row in cursor.fetchall()]


def columns(cursor, table):
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s
             AND is_generated = 'NEVER'
           ORDER BY ordinal_position""",
        (SCHEMA, table),
    )
    return [row[0] for row in cursor.fetchall()]


def qualified(table):
    return sql.Identifier(SCHEMA, table)


def copy_command(table, names, direction):
    fields = sql.SQL(", ").join(sql.Identifier(name) for name in names)
    return sql.SQL("COPY {} ({}) {} STD{} WITH (FORMAT csv, HEADER true, NULL {})").format(
        qualified(table),
        fields,
        sql.SQL("TO" if direction == "export" else "FROM"),
        sql.SQL("OUT" if direction == "export" else "IN"),
        sql.Literal(NULL_MARKER),
    )


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def export_directory(destination):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError(f"Export destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".vogelvrij-export-", dir=destination.parent))
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                names = tables(cursor)
                if not names:
                    raise ValueError("No public application tables found")
                manifest = {"format_version": 1, "schema": SCHEMA, "tables": []}
                for table in names:
                    fields = columns(cursor, table)
                    if not fields:
                        raise ValueError(f"Table {table} has no exportable columns")
                    path = temporary / f"{table}.csv"
                    with path.open("wb") as output:
                        with cursor.copy(copy_command(table, fields, "export")) as source:
                            for chunk in source:
                                output.write(chunk)
                    cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(qualified(table)))
                    manifest["tables"].append(
                        {"name": table, "columns": fields, "rows": cursor.fetchone()[0],
                         "sha256": digest(path)}
                    )
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        temporary.rename(destination)
        return manifest
    except BaseException:
        shutil.rmtree(temporary)
        raise


def dependency_order(cursor, names):
    cursor.execute(
        """SELECT child.relname, parent.relname
           FROM pg_constraint constraint_row
           JOIN pg_class child ON child.oid = constraint_row.conrelid
           JOIN pg_namespace child_schema ON child_schema.oid = child.relnamespace
           JOIN pg_class parent ON parent.oid = constraint_row.confrelid
           JOIN pg_namespace parent_schema ON parent_schema.oid = parent.relnamespace
           WHERE constraint_row.contype = 'f'
             AND child_schema.nspname = %s AND parent_schema.nspname = %s""",
        (SCHEMA, SCHEMA),
    )
    pending = {name: set() for name in names}
    for child, parent in cursor.fetchall():
        if child != parent and child in pending and parent in pending:
            pending[child].add(parent)
    ordered = []
    while pending:
        ready = sorted(name for name, parents in pending.items() if not parents)
        if not ready:
            raise ValueError("Foreign-key cycle prevents CSV import")
        for name in ready:
            ordered.append(name)
            del pending[name]
        for parents in pending.values():
            parents.difference_update(ready)
    return ordered


def validate_manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported export manifest")
    entries = manifest.get("tables")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Export manifest contains no tables")
    names = [entry["name"] for entry in entries]
    if len(set(names)) != len(names) or any(Path(name).name != name for name in names):
        raise ValueError("Invalid or duplicate table name in manifest")
    for entry in entries:
        fields = entry["columns"]
        if not fields or len(set(fields)) != len(fields):
            raise ValueError(f"Invalid columns in manifest: {entry['name']}")
        if not isinstance(entry["rows"], int) or entry["rows"] < 0:
            raise ValueError(f"Invalid row count in manifest: {entry['name']}")
        path = directory / f"{entry['name']}.csv"
        if digest(path) != entry["sha256"]:
            raise ValueError(f"CSV checksum mismatch: {path}")
    return {entry["name"]: entry for entry in entries}


def reset_sequences(cursor, table, fields):
    for field in fields:
        cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (f"{SCHEMA}.{table}", field))
        sequence = cursor.fetchone()[0]
        if sequence:
            cursor.execute(
                sql.SQL("SELECT setval(%s::regclass, COALESCE(max({}), 1), "
                        "max({}) IS NOT NULL) FROM {}").format(
                    sql.Identifier(field), sql.Identifier(field), qualified(table)
                ),
                (sequence,),
            )


def import_directory(source):
    source = Path(source).expanduser().resolve()
    entries = validate_manifest(source)
    with connect() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                current = tables(cursor)
                if set(current) != set(entries):
                    raise ValueError(
                        "Target public tables do not match the export; apply migrations first"
                    )
                for table in current:
                    cursor.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                        qualified(table)
                    ))
                for table in current:
                    fields = columns(cursor, table)
                    if set(fields) != set(entries[table]["columns"]) or len(fields) != len(
                        entries[table]["columns"]
                    ):
                        raise ValueError(f"Target columns do not match export: {table}")
                    cursor.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                        qualified(table)
                    ))
                    if cursor.fetchone()[0]:
                        raise ValueError(f"Target table is not empty: {table}")
                for table in dependency_order(cursor, current):
                    entry = entries[table]
                    with (source / f"{table}.csv").open("rb") as input_file:
                        with cursor.copy(copy_command(table, entry["columns"], "import")) as target:
                            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                                target.write(chunk)
                    cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(qualified(table)))
                    if cursor.fetchone()[0] != entry["rows"]:
                        raise ValueError(f"Imported row count does not match: {table}")
                    reset_sequences(cursor, table, entry["columns"])
    return entries


def main_export():
    parser = argparse.ArgumentParser(description="Export all public database tables to CSV")
    parser.add_argument("directory", help="New directory for CSV files and manifest.json")
    args = parser.parse_args()
    try:
        manifest = export_directory(args.directory)
    except (OSError, ValueError, psycopg.Error) as error:
        parser.exit(1, f"Export failed: {error}\n")
    print(f"Exported {len(manifest['tables'])} tables to {args.directory}")


def main_import():
    parser = argparse.ArgumentParser(description="Import CSV files into an empty migrated database")
    parser.add_argument("directory", help="Directory created by export-database.py")
    args = parser.parse_args()
    try:
        entries = import_directory(args.directory)
    except (OSError, ValueError, json.JSONDecodeError, psycopg.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    print(f"Imported {len(entries)} tables from {args.directory}")
