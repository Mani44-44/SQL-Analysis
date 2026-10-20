"""Create (or recreate) the public demo workspace from the seeded generator.

Usage:  python -m app.demo.seed [--force]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DataSource, GlossaryTerm, Workspace
from app.demo.generate import DEFAULT_SEED, DEMO_GLOSSARY, generate
from app.services.ingestion.service import (
    delete_workspace_data,
    ingest_source,
    source_file_path,
)

logger = logging.getLogger(__name__)

DEMO_NAME = "Personal Finance (demo)"
DEMO_TABLE_DESCRIPTIONS = {
    "transactions": "Every bank, card, wallet and UPI transaction from Jan 2025 to Jun 2026. "
    "amount is always positive in INR; type says whether money left (Debit) or arrived (Credit).",
    "accounts": "The user's bank accounts, credit card and wallet.",
    "merchants": "Canonical merchant list; each merchant belongs to one spending category.",
    "categories": "Spending / income categories grouped into Needs, Wants, Income, Savings, Transfers.",
    "budgets": "Monthly budget in INR per category; month is the first day of the month.",
}


def seed_demo(
    db: Session, *, force: bool = False, seed: int = DEFAULT_SEED, describe: bool = False
) -> Workspace:
    existing = db.scalars(select(Workspace).where(Workspace.is_demo.is_(True))).first()
    if existing and not force:
        return existing
    if existing:
        ws_id = existing.id
        db.delete(existing)
        db.commit()
        delete_workspace_data(ws_id)

    ws = Workspace(name=DEMO_NAME, is_demo=True)
    db.add(ws)
    db.commit()

    with tempfile.TemporaryDirectory() as tmp:
        files = generate(Path(tmp), seed)
        for path in files.values():
            src = DataSource(
                workspace_id=ws.id,
                type="xlsx" if path.suffix == ".xlsx" else "csv",
                filename=path.name,
            )
            db.add(src)
            db.commit()
            dest = source_file_path(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, dest)
            result = ingest_source(db, src.id, describe=describe)
            if result.status != "ready":
                raise RuntimeError(f"demo ingestion failed for {path.name}: {result.error}")

    for term, definition in DEMO_GLOSSARY:
        db.add(GlossaryTerm(workspace_id=ws.id, term=term, definition=definition))
    from app.db.models import TableMeta

    for t in db.scalars(select(TableMeta).where(TableMeta.workspace_id == ws.id)):
        if t.name in DEMO_TABLE_DESCRIPTIONS:
            t.description = DEMO_TABLE_DESCRIPTIONS[t.name]
    db.commit()
    logger.info("demo_seeded", extra={"workspace_id": ws.id})
    return ws


def main() -> None:  # pragma: no cover
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.migrate import upgrade_to_head
    from app.db.session import get_sessionmaker

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="drop and recreate the demo workspace")
    p.add_argument("--describe", action="store_true", help="draft column descriptions with the LLM")
    args = p.parse_args()
    s = get_settings()
    configure_logging(s.log_level, json_logs=False)
    s.workspaces_dir.mkdir(parents=True, exist_ok=True)
    upgrade_to_head()
    db = get_sessionmaker()()
    try:
        ws = seed_demo(db, force=args.force, describe=args.describe)
        print(f"demo workspace: {ws.id}")
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
