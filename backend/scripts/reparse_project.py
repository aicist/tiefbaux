"""Reparse a stored LV project with the current parser, updating positions in place.

Usage: python -m scripts.reparse_project <project_id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import LVProject, LVProjectPosition
from app.services.llm_parser import parse_lv_with_llm


def main(project_id: int) -> None:
    with SessionLocal() as session:
        project = session.get(LVProject, project_id)
        if project is None:
            raise SystemExit(f"Project {project_id} not found")
        if not project.pdf_path:
            raise SystemExit(f"Project {project_id} has no stored pdf_path")

        pdf_file = Path(project.pdf_path)
        if not pdf_file.is_absolute():
            pdf_file = Path(__file__).resolve().parent.parent / pdf_file
        if not pdf_file.exists():
            raise SystemExit(f"PDF file missing: {pdf_file}")

        print(f"Re-parsing {project.filename} ({pdf_file})...")
        pdf_bytes = pdf_file.read_bytes()
        positions, _metadata = parse_lv_with_llm(pdf_bytes)
        print(f"  got {len(positions)} positions from parser")

        existing_rows = session.scalars(
            select(LVProjectPosition).where(LVProjectPosition.project_id == project_id)
        ).all()
        by_oz = {row.ordnungszahl: row for row in existing_rows}

        updated = 0
        for pos in positions:
            row = by_oz.get(pos.ordnungszahl)
            if row is None:
                continue
            row.description = pos.description
            row.raw_text = pos.raw_text
            row.quantity = pos.quantity
            row.unit = pos.unit
            row.billable = pos.billable
            row.position_type = pos.position_type
            row.parameters_json = json.dumps(
                pos.parameters.model_dump(exclude_none=False), ensure_ascii=False
            )
            updated += 1

        session.commit()
        print(f"  updated {updated} existing positions in DB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.reparse_project <project_id>")
    main(int(sys.argv[1]))
