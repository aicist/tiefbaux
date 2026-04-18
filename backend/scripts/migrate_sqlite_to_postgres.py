"""Copy all data from the local SQLite DB to a Postgres target (e.g. Supabase).

Usage:
    SQLITE_URL=sqlite:///./tiefbaux.db \
    TARGET_DATABASE_URL=postgresql://user:pw@host:5432/postgres \
    python -m scripts.migrate_sqlite_to_postgres

The target schema is created from SQLAlchemy models (Base.metadata.create_all).
Existing rows in target tables are preserved; this script only INSERTs new rows
by primary key. Safe to re-run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import Base
from app import models  # noqa: F401  — ensures all models are registered on Base


def _resolve_url(raw: str) -> str:
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def main() -> None:
    sqlite_url = os.getenv("SQLITE_URL", "sqlite:///./tiefbaux.db")
    target_url = os.getenv("TARGET_DATABASE_URL")
    if not target_url:
        raise SystemExit("TARGET_DATABASE_URL is required")

    backend_dir = Path(__file__).resolve().parent.parent
    if sqlite_url.startswith("sqlite:///./"):
        sqlite_url = f"sqlite:///{backend_dir / sqlite_url.replace('sqlite:///./', '')}"

    target_url = _resolve_url(target_url)

    print(f"Source:  {sqlite_url}")
    print(f"Target:  {target_url.split('@')[-1]}")

    src_engine = create_engine(sqlite_url, future=True)
    dst_engine = create_engine(target_url, future=True, pool_pre_ping=True)

    print("Creating target schema...")
    Base.metadata.create_all(dst_engine)

    ordered_tables = Base.metadata.sorted_tables
    is_postgres = dst_engine.dialect.name == "postgresql"
    wipe = os.getenv("WIPE", "").lower() in ("1", "true", "yes")

    # Collect valid PKs per table from the SOURCE to validate FK references.
    valid_pks: dict[str, set] = {}

    with Session(src_engine) as src, Session(dst_engine) as dst:
        if wipe and is_postgres:
            names = ", ".join(f'"{t.name}"' for t in ordered_tables)
            print(f"WIPE=1: TRUNCATE {names} RESTART IDENTITY CASCADE")
            dst.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
            dst.commit()
        for table in ordered_tables:
            rows = src.execute(select(table)).mappings().all()

            # Record valid PKs from source for FK validation of later tables.
            pk_cols = [c.name for c in table.primary_key.columns]
            if pk_cols:
                if len(pk_cols) == 1:
                    valid_pks[table.name] = {r[pk_cols[0]] for r in rows if r[pk_cols[0]] is not None}
                else:
                    valid_pks[table.name] = {tuple(r[c] for c in pk_cols) for r in rows}

            if not rows:
                print(f"  {table.name}: empty")
                continue

            # FK sanity: for each FK column, if its value doesn't reference an
            # existing row in the source, set to NULL (if nullable) or drop row.
            fk_fixes = []  # list of (column_name, referenced_table, nullable)
            for col in table.columns:
                for fk in col.foreign_keys:
                    ref_table = fk.column.table.name
                    fk_fixes.append((col.name, ref_table, col.nullable))

            payload = []
            dropped = 0
            for row in rows:
                data = dict(row)
                skip_row = False
                for col_name, ref_table, nullable in fk_fixes:
                    value = data.get(col_name)
                    if value is None:
                        continue
                    if value not in valid_pks.get(ref_table, set()):
                        if nullable:
                            data[col_name] = None
                        else:
                            skip_row = True
                            break
                if skip_row:
                    dropped += 1
                else:
                    payload.append(data)

            if not payload:
                print(f"  {table.name}: empty after FK cleanup (dropped {dropped})")
                continue

            if is_postgres:
                stmt = pg_insert(table).on_conflict_do_nothing()
                result = dst.execute(stmt, payload)
                inserted = result.rowcount if result.rowcount is not None else len(payload)
                suffix = f" (dropped {dropped} dangling-FK rows)" if dropped else ""
                print(f"  {table.name}: inserted {inserted} / {len(rows)} rows{suffix}")
            else:
                dst.execute(table.insert(), payload)
                print(f"  {table.name}: inserted {len(payload)} rows")

        dst.commit()

        if is_postgres:
            print("Resetting Postgres sequences...")
            for table in ordered_tables:
                for col in table.primary_key.columns:
                    if col.autoincrement and col.type.python_type is int:
                        dst.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col.name}'), "
                            f"COALESCE((SELECT MAX({col.name}) FROM {table.name}), 1), "
                            f"(SELECT MAX({col.name}) FROM {table.name}) IS NOT NULL)"
                        ))
            dst.commit()

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
