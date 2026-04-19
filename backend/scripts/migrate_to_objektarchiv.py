"""One-off migration to Objektarchiv schema.

- Snapshots the Mustermann demo project (id=8) in memory
- Wipes lv_projects, lv_project_positions, project_files, objekte, kunden
- Clears project_id FKs on tenders/supplier_inquiries/supplier_offers
- Drops + recreates lv_projects table via Base.metadata.create_all to add
  objekt_id/kunde_id FKs and composite unique (objekt_id, kunde_id, content_hash)
- Re-inserts Muster-Objekt + Muster-Kunde + LVProject (with positions,
  selections_json, workstate_json, pdf_path, project_files blob)

Idempotent: safe to re-run. Creates a backup file first.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, engine  # noqa: E402
from app.models import (  # noqa: E402
    Kunde,
    LVProject,
    LVProjectPosition,
    Objekt,
    ProjectFile,
)
from app.services.archive_resolvers import (  # noqa: E402
    build_kunde_slug,
    build_objekt_slug,
)
from sqlalchemy.orm import Session  # noqa: E402


DB_PATH = BACKEND_DIR / "tiefbaux.db"
BACKUP_PATH = BACKEND_DIR / "tiefbaux.pre_objektarchiv.bak"


def snapshot_mustermann(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM lv_projects WHERE id = 8")
    proj = cur.fetchone()
    if proj is None:
        raise RuntimeError("Mustermann project id=8 not found — aborting")

    cur.execute("SELECT * FROM lv_project_positions WHERE project_id = 8 ORDER BY id")
    positions = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT kind, filename, content FROM project_files WHERE project_id = 8")
    files = [dict(r) for r in cur.fetchall()]

    return {"project": dict(proj), "positions": positions, "files": files}


def main() -> None:
    print(f"Backing up {DB_PATH} → {BACKUP_PATH}")
    shutil.copy2(DB_PATH, BACKUP_PATH)

    raw = sqlite3.connect(DB_PATH)
    snap = snapshot_mustermann(raw)
    print(
        f"Snapshot: project P-2604-008 '{snap['project']['bauvorhaben']}', "
        f"{len(snap['positions'])} positions, {len(snap['files'])} files"
    )

    cur = raw.cursor()
    print("Clearing FKs and wiping project tables…")
    cur.execute("UPDATE tenders SET project_id = NULL WHERE project_id IS NOT NULL")
    cur.execute("UPDATE supplier_inquiries SET project_id = NULL WHERE project_id IS NOT NULL")
    cur.execute("UPDATE supplier_offers SET project_id = NULL WHERE project_id IS NOT NULL")
    cur.execute("DELETE FROM project_files")
    cur.execute("DELETE FROM lv_project_positions")
    cur.execute("DELETE FROM lv_projects")
    cur.execute("DELETE FROM kunden")
    cur.execute("DELETE FROM objekte")

    print("Dropping lv_projects to force re-create with new columns…")
    cur.execute("DROP TABLE lv_projects")
    raw.commit()
    raw.close()

    print("Recreating tables via SQLAlchemy metadata…")
    Base.metadata.create_all(engine)

    print("Inserting Muster-Objekt + Muster-Kunde + Projekt…")
    proj_row = snap["project"]
    with Session(engine) as db:
        objekt_slug = build_objekt_slug(
            proj_row["bauvorhaben"], proj_row["objekt_nr"], proj_row["auftraggeber"]
        )
        objekt = Objekt(
            slug=objekt_slug,
            bauvorhaben=proj_row["bauvorhaben"],
            objekt_nr=proj_row["objekt_nr"],
            auftraggeber=proj_row["auftraggeber"],
            submission_date=proj_row["submission_date"],
        )
        db.add(objekt)
        db.flush()

        muster_name = "Bauunternehmung Mustermann"
        kunde_slug = build_kunde_slug(muster_name, None)
        kunde = Kunde(
            slug=kunde_slug,
            name=muster_name,
            display_name=muster_name,
            email_domain=None,
        )
        db.add(kunde)
        db.flush()

        project = LVProject(
            content_hash=proj_row["content_hash"],
            objekt_id=objekt.id,
            kunde_id=kunde.id,
            filename=proj_row["filename"],
            project_name=proj_row["project_name"],
            total_positions=proj_row["total_positions"] or 0,
            billable_positions=proj_row["billable_positions"] or 0,
            service_positions=proj_row["service_positions"] or 0,
            bauvorhaben=proj_row["bauvorhaben"],
            objekt_nr=proj_row["objekt_nr"],
            submission_date=proj_row["submission_date"],
            auftraggeber=proj_row["auftraggeber"],
            kunde_name=muster_name,
            kunde_adresse=proj_row["kunde_adresse"],
            projekt_nr=proj_row["projekt_nr"],
            selections_json=proj_row["selections_json"],
            workstate_json=proj_row["workstate_json"],
            pdf_path=proj_row["pdf_path"],
            status=proj_row["status"] or "offen",
            offer_pdf_path=proj_row["offer_pdf_path"],
            assigned_user_id=proj_row["assigned_user_id"],
            last_editor_id=proj_row["last_editor_id"],
        )
        db.add(project)
        db.flush()

        for pos in snap["positions"]:
            db.add(
                LVProjectPosition(
                    project_id=project.id,
                    position_id=pos["position_id"],
                    ordnungszahl=pos["ordnungszahl"],
                    description=pos["description"],
                    raw_text=pos["raw_text"],
                    quantity=pos["quantity"],
                    unit=pos["unit"],
                    billable=bool(pos["billable"]),
                    position_type=pos["position_type"],
                    parameters_json=pos["parameters_json"],
                    source_page=pos["source_page"],
                )
            )

        for f in snap["files"]:
            db.add(
                ProjectFile(
                    project_id=project.id,
                    kind=f["kind"],
                    filename=f["filename"],
                    content=f["content"],
                )
            )

        db.commit()
        print(
            f"Done. Objekt #{objekt.id} slug={objekt.slug}, Kunde #{kunde.id} slug={kunde.slug}, "
            f"Project #{project.id} projekt_nr={project.projekt_nr}"
        )


if __name__ == "__main__":
    main()
