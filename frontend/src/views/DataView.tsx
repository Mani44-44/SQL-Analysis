"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkspace } from "@/components/WorkspaceShell";
import { Button, Empty, Notice, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, type ColumnCard, type GlossaryTerm, type Source, type TableCard, type WorkspaceSchema } from "@/lib/api";
import { humanise, timeAgo } from "@/lib/format";

const TYPES = ["text", "integer", "float", "currency", "percent", "boolean", "date", "timestamp"];

export default function DataPage() {
  const ws = useWorkspace();
  const readOnly = ws.is_demo;
  const [sources, setSources] = useState<Source[]>([]);
  const [schema, setSchema] = useState<WorkspaceSchema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, sc] = await Promise.all([api.sources(ws.id), api.schema(ws.id)]);
      setSources(s);
      setSchema(sc);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [ws.id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while anything is still ingesting.
  useEffect(() => {
    if (!sources.some((s) => s.status === "pending" || s.status === "processing")) return;
    const t = setTimeout(refresh, 1500);
    return () => clearTimeout(t);
  }, [sources, refresh]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const f of Array.from(files)) await api.upload(ws.id, f);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removeSource(s: Source) {
    if (!window.confirm(`Delete ${s.filename} and its tables (${s.tables.join(", ") || "none"})? This can't be undone.`)) return;
    try {
      await api.deleteSource(s.id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Data">{readOnly && <Pill>Demo data is read-only</Pill>}</PageHeader>
      {error && (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {!readOnly && (
        <section aria-labelledby="upload-h" className="mb-10">
          <h2 id="upload-h" className="sr-only">
            Upload files
          </h2>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              upload(e.dataTransfer.files);
            }}
            className={`rounded-lg border-2 border-dashed px-6 py-8 text-center ${dragging ? "border-accent bg-accent-soft" : "border-rule"}`}
          >
            <p className="font-display text-lg">Drop a CSV, Excel or SQLite file here</p>
            <p className="mt-1 text-sm text-muted">Up to 50 MB. Messy headers, ₹ amounts and mixed date formats are cleaned up for you.</p>
            <input ref={fileRef} type="file" multiple accept=".csv,.tsv,.txt,.xlsx,.sqlite,.sqlite3,.db" className="sr-only" id="file" onChange={(e) => upload(e.target.files)} />
            <Button variant="primary" className="mt-4" busy={uploading} onClick={() => fileRef.current?.click()}>
              Choose files
            </Button>
          </div>
        </section>
      )}

      <section aria-labelledby="sources-h" className="mb-10">
        <h2 id="sources-h" className="font-display text-lg font-medium">
          Files
        </h2>
        {sources.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No files yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-rule-soft border-y border-rule-soft">
            {sources.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <span className="font-medium">{s.filename}</span>
                {s.status === "ready" ? (
                  <Pill tone="accent">Ready</Pill>
                ) : s.status === "failed" ? (
                  <Pill tone="stamp">Failed</Pill>
                ) : (
                  <span className="flex items-center gap-1.5 text-muted">
                    <Spinner /> Processing
                  </span>
                )}
                <span className="text-muted">{s.tables.length ? `→ ${s.tables.join(", ")}` : ""}</span>
                <span className="ml-auto text-muted">{timeAgo(s.created_at)}</span>
                {!readOnly && (
                  <button type="button" className="text-stamp hover:underline" onClick={() => removeSource(s)}>
                    Delete
                  </button>
                )}
                {s.error && <p className="basis-full text-stamp">{s.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="schema-h" className="mb-10">
        <h2 id="schema-h" className="font-display text-lg font-medium">
          Tables
        </h2>
        <p className="mt-1 text-sm text-muted">Descriptions help AskData pick the right columns. Fix any column type it guessed wrong.</p>
        {!schema ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-muted">
            <Spinner /> Loading
          </p>
        ) : schema.tables.length === 0 ? (
          <div className="mt-4">
            <Empty title="No tables yet">Upload a file above and its tables will appear here.</Empty>
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {schema.tables.map((t) => (
              <TableBlock key={t.id} table={t} readOnly={readOnly} onSchema={setSchema} onError={setError} />
            ))}
          </div>
        )}
        {schema && schema.join_hints.length > 0 && (
          <p className="mt-4 text-sm text-muted">
            Detected join keys: {schema.join_hints.map((h) => `${h.left_table}.${h.left_column} = ${h.right_table}.${h.right_column}`).join("; ")}
          </p>
        )}
      </section>

      <Glossary terms={schema?.glossary ?? []} readOnly={readOnly} onChange={refresh} />
    </div>
  );
}

function TableBlock({
  table,
  readOnly,
  onSchema,
  onError,
}: {
  table: TableCard;
  readOnly: boolean;
  onSchema: (s: WorkspaceSchema) => void;
  onError: (m: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [desc, setDesc] = useState(table.description ?? "");
  return (
    <div className="rounded-lg border border-rule bg-raised">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-baseline gap-x-3 px-4 py-3 text-left">
        <span className="font-mono text-[15px] font-medium">{table.name}</span>
        <span className="text-sm text-muted">
          {table.row_count.toLocaleString("en-IN")} rows, {table.columns.length} columns
        </span>
        {table.description && <span className="basis-full truncate text-sm text-ink-soft">{table.description}</span>}
      </button>
      {open && (
        <div className="border-t border-rule px-4 pb-4">
          {!readOnly && (
            <div className="mt-3 flex gap-2">
              <label className="sr-only" htmlFor={`td-${table.id}`}>
                Table description
              </label>
              <input
                id={`td-${table.id}`}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                placeholder="Describe what this table holds"
                className="min-w-0 flex-1 rounded border border-rule bg-paper px-2 py-1.5 text-sm"
              />
              <Button onClick={() => api.patchTable(table.id, desc).then(onSchema, (e) => onError(e.message))} disabled={desc === (table.description ?? "")}>
                Save
              </Button>
            </div>
          )}
          <div className="mt-3 overflow-x-auto">
            <table className="ledger w-full text-sm">
              <thead>
                <tr className="border-b-2 border-rule text-left">
                  <th scope="col" className="px-2 py-2 font-medium">Column</th>
                  <th scope="col" className="px-2 py-2 font-medium">Type</th>
                  <th scope="col" className="px-2 py-2 font-medium">Description</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Empty</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Distinct</th>
                  <th scope="col" className="px-2 py-2 font-medium">Examples</th>
                </tr>
              </thead>
              <tbody>
                {table.columns.map((c) => (
                  <ColumnRow key={c.id} col={c} readOnly={readOnly} onSchema={onSchema} onError={onError} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ColumnRow({ col, readOnly, onSchema, onError }: { col: ColumnCard; readOnly: boolean; onSchema: (s: WorkspaceSchema) => void; onError: (m: string) => void }) {
  const [desc, setDesc] = useState(col.description ?? "");
  const [busy, setBusy] = useState(false);
  const examples = col.top_values.length ? col.top_values.map((v) => v.value) : col.sample_values;

  async function patch(body: Parameters<typeof api.patchColumn>[1]) {
    setBusy(true);
    try {
      onSchema(await api.patchColumn(col.id, body));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="align-top">
      <td className="px-2 py-1.5">
        <span className="font-mono">{col.name}</span>
        {col.original_name && col.original_name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") !== col.name && (
          <span className="block text-xs text-muted">from “{col.original_name}”</span>
        )}
      </td>
      <td className="px-2 py-1.5">
        {readOnly ? (
          humanise(col.type)
        ) : (
          <select
            aria-label={`Type of ${col.name}`}
            value={col.type}
            disabled={busy}
            onChange={(e) => patch({ type_override: e.target.value })}
            className="rounded border border-rule bg-paper px-1 py-0.5"
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {humanise(t)}
              </option>
            ))}
          </select>
        )}
        {col.type_overridden && !readOnly && (
          <button type="button" className="block text-xs text-accent hover:underline" onClick={() => patch({ clear_type_override: true })}>
            Reset to detected
          </button>
        )}
      </td>
      <td className="min-w-56 px-2 py-1.5">
        {readOnly ? (
          <span className="text-ink-soft">{col.description ?? "—"}</span>
        ) : (
          <input
            aria-label={`Description of ${col.name}`}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            onBlur={() => desc !== (col.description ?? "") && patch({ description: desc })}
            placeholder="Add a description"
            className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 hover:border-rule focus:border-rule focus:bg-paper"
          />
        )}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">{col.null_pct ? `${col.null_pct}%` : "—"}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">{col.distinct_count.toLocaleString("en-IN")}</td>
      <td className="max-w-64 truncate px-2 py-1.5 text-muted" title={examples.join(", ")}>
        {examples.slice(0, 3).join(", ")}
      </td>
    </tr>
  );
}

function Glossary({ terms, readOnly, onChange }: { terms: GlossaryTerm[]; readOnly: boolean; onChange: () => void }) {
  const ws = useWorkspace();
  const [term, setTerm] = useState("");
  const [definition, setDefinition] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <section aria-labelledby="glossary-h">
      <h2 id="glossary-h" className="font-display text-lg font-medium">
        Business terms
      </h2>
      <p className="mt-1 text-sm text-muted">Tell AskData what your words mean, e.g. what counts as “spend”. These definitions are used when writing SQL.</p>
      {terms.length > 0 && (
        <dl className="mt-3 divide-y divide-rule-soft border-y border-rule-soft">
          {terms.map((g) => (
            <div key={g.id} className="grid gap-1 py-2.5 text-sm md:grid-cols-[12rem_1fr_auto]">
              <dt className="font-medium">{g.term}</dt>
              <dd className="text-ink-soft">{g.definition}</dd>
              {!readOnly && (
                <button type="button" className="justify-self-start text-stamp hover:underline" onClick={() => api.deleteGlossary(g.id).then(onChange, (e) => setError(e.message))}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </dl>
      )}
      {!readOnly && (
        <form
          className="mt-3 grid gap-2 md:grid-cols-[12rem_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            api.addGlossary(ws.id, term, definition).then(() => {
              setTerm("");
              setDefinition("");
              onChange();
            }, (err) => setError(err.message));
          }}
        >
          <input aria-label="Term" required value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Term" className="rounded border border-rule bg-paper px-2 py-1.5 text-sm" />
          <input aria-label="Definition" required value={definition} onChange={(e) => setDefinition(e.target.value)} placeholder="What it means in terms of your columns" className="rounded border border-rule bg-paper px-2 py-1.5 text-sm" />
          <Button type="submit">Add term</Button>
        </form>
      )}
      {error && (
        <div className="mt-2">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
    </section>
  );
}
