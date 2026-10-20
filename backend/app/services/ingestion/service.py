"""Ingestion orchestration: read -> clean -> infer -> load into DuckDB -> profile -> metadata.

Re-ingesting a source (e.g. after a column type override) preserves user-edited descriptions and
type overrides, keyed by (table, column).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.models import ColumnMeta, DataSource, TableMeta
from app.services.ingestion import loader
from app.services.ingestion.clean import clean_table
from app.services.ingestion.infer import LOGICAL_TYPES, LogicalType, convert, infer_column
from app.services.ingestion.readers import UnsupportedFileError, read_file
from app.services.storage import source_upload_dir, workspace_db_path, workspace_lock

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


def source_file_path(source: DataSource) -> Path:
    return source_upload_dir(source.workspace_id, source.id) / Path(source.filename).name


def _unique_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def ingest_source(db: Session, source_id: str, *, describe: bool = True) -> DataSource:
    settings = get_settings()
    source = db.get(DataSource, source_id)
    if source is None:
        raise IngestionError("source not found")

    # Preserve user edits across re-ingestion.
    previous = db.scalars(
        select(TableMeta)
        .where(TableMeta.source_id == source.id)
        .options(selectinload(TableMeta.columns))
    ).all()
    kept_table_desc = {t.name: t.description for t in previous if t.description}
    kept_col: dict[tuple[str, str], tuple[str | None, str | None]] = {
        (t.name, c.name): (c.description, c.type_override) for t in previous for c in t.columns
    }
    previous_names = [t.name for t in previous]

    source.status, source.error = "processing", None
    db.commit()

    try:
        raw_tables = read_file(source_file_path(source), source.type, settings.max_upload_rows)
        taken = set(
            db.scalars(
                select(TableMeta.name).where(
                    TableMeta.workspace_id == source.workspace_id,
                    TableMeta.source_id != source.id,
                )
            )
        )
        db_path = workspace_db_path(source.workspace_id)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        built: list[tuple[str, list[loader.TypedColumn]]] = []
        for raw in raw_tables:
            cleaned = clean_table(raw)
            if not cleaned.columns:
                continue
            table_name = _unique_name(cleaned.name, taken)
            taken.add(table_name)
            typed: list[loader.TypedColumn] = []
            for idx, col in enumerate(cleaned.columns):
                values = [r[idx] for r in cleaned.rows]
                override = kept_col.get((table_name, col), (None, None))[1]
                if override in LOGICAL_TYPES:
                    forced = convert(values, override, threshold=0.0)
                    assert forced is not None
                    inferred = forced
                else:
                    inferred = infer_column(values, settings.date_parse_threshold)
                typed.append(
                    loader.TypedColumn(
                        name=col,
                        original_name=cleaned.original_columns[idx],
                        logical_type=inferred.logical_type,
                        values=inferred.values,
                        coerced_nulls=inferred.coerced_nulls,
                    )
                )
            built.append((table_name, typed))

        if not built:
            raise IngestionError("no tables with columns were found in the file")

        profiles: list[tuple[loader.TableProfile, list[loader.TypedColumn]]] = []
        with workspace_lock(source.workspace_id).write():
            con = duckdb.connect(str(db_path))
            try:
                for name in previous_names:
                    loader.drop_table(con, name)
                for table_name, typed in built:
                    loader.load_table(con, table_name, typed)
                    prof = loader.profile_table(
                        con, table_name, [(c.name, c.logical_type) for c in typed]
                    )
                    profiles.append((prof, typed))
                con.execute("CHECKPOINT")
            finally:
                con.close()

        for t in previous:
            db.delete(t)
        db.flush()
        new_tables: list[TableMeta] = []
        for prof, typed in profiles:
            tm = TableMeta(
                source_id=source.id,
                workspace_id=source.workspace_id,
                name=prof.name,
                row_count=prof.row_count,
                description=kept_table_desc.get(prof.name),
            )
            for pos, (cp, tc) in enumerate(zip(prof.columns, typed, strict=True)):
                desc, override = kept_col.get((prof.name, cp.name), (None, None))
                tm.columns.append(
                    ColumnMeta(
                        position=pos,
                        name=cp.name,
                        original_name=tc.original_name,
                        type=cp.logical_type,
                        type_override=override,
                        null_pct=cp.null_pct,
                        distinct_count=cp.distinct_count,
                        min_value=cp.min_value,
                        max_value=cp.max_value,
                        top_values=cp.top_values,
                        sample_values=cp.sample_values,
                        description=desc,
                    )
                )
            db.add(tm)
            new_tables.append(tm)
        source.status = "ready"
        db.commit()
        logger.info(
            "ingest_ok",
            extra={
                "source_id": source.id,
                "tables": [t.name for t in new_tables],
                "rows": sum(t.row_count for t in new_tables),
            },
        )
    except (UnsupportedFileError, IngestionError, duckdb.Error, ValueError) as e:
        db.rollback()
        source = db.get(DataSource, source_id)
        assert source is not None
        source.status, source.error = "failed", str(e)[:1000]
        db.commit()
        logger.warning("ingest_failed", extra={"source_id": source_id, "error": str(e)})
        return source

    if describe:
        from app.services.llm import get_provider
        from app.services.schema.describe import draft_descriptions

        provider = get_provider()
        for tm in new_tables:
            draft_descriptions(db, tm, provider)
    return source


def run_ingestion_job(source_id: str) -> None:
    """Background-task entrypoint with its own DB session."""
    from app.db.session import get_sessionmaker

    db = get_sessionmaker()()
    try:
        ingest_source(db, source_id)
    except Exception:  # pragma: no cover - last-resort guard for background jobs
        logger.exception("ingest_crashed", extra={"source_id": source_id})
        db.rollback()
        src = db.get(DataSource, source_id)
        if src is not None:
            src.status, src.error = "failed", "internal error during ingestion"
            db.commit()
    finally:
        db.close()


def delete_source_data(db: Session, source: DataSource) -> None:
    names = list(db.scalars(select(TableMeta.name).where(TableMeta.source_id == source.id)))
    path = workspace_db_path(source.workspace_id)
    if names and path.exists():
        with workspace_lock(source.workspace_id).write():
            con = duckdb.connect(str(path))
            try:
                for n in names:
                    loader.drop_table(con, n)
                con.execute("CHECKPOINT")
            finally:
                con.close()
    shutil.rmtree(source_upload_dir(source.workspace_id, source.id), ignore_errors=True)


def delete_workspace_data(workspace_id: str) -> None:
    with workspace_lock(workspace_id).write():
        for suffix in ("", ".wal"):
            p = Path(str(workspace_db_path(workspace_id)) + suffix)
            p.unlink(missing_ok=True)
    shutil.rmtree(get_settings().uploads_dir / workspace_id, ignore_errors=True)


def logical_type_or_none(value: str | None) -> LogicalType | None:
    return value if value in LOGICAL_TYPES else None
