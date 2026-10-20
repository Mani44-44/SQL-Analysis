"use client";

import { useMemo, useState } from "react";
import type { Cell } from "@/lib/api";
import { formatCell, humanise } from "@/lib/format";

const PAGE = 25;

function compare(a: Cell, b: Cell): number {
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en-IN", { numeric: true });
}

export function ResultTable({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => sort.dir * compare(a[sort.col], b[sort.col]));
  }, [rows, sort]);

  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const view = sorted.slice(page * PAGE, page * PAGE + PAGE);
  const numeric = columns.map((_, i) => rows.some((r) => typeof r[i] === "number"));

  if (!rows.length) return <p className="py-3 text-sm text-muted">No rows.</p>;

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="ledger w-full border-collapse text-sm">
          <thead>
            <tr className="border-b-2 border-rule text-left">
              {columns.map((c, i) => {
                const active = sort?.col === i;
                return (
                  <th key={c} scope="col" aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : "none"} className={`whitespace-nowrap px-2 py-2 font-medium ${numeric[i] ? "text-right" : ""}`}>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-accent"
                      onClick={() => {
                        setPage(0);
                        setSort(active ? { col: i, dir: sort!.dir === 1 ? -1 : 1 } : { col: i, dir: numeric[i] ? -1 : 1 });
                      }}
                    >
                      {humanise(c)}
                      <span aria-hidden className="text-xs text-muted">{active ? (sort!.dir === 1 ? "▲" : "▼") : ""}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {view.map((r, ri) => (
              <tr key={ri}>
                {r.map((v, ci) => (
                  <td key={ci} className={`px-2 py-1.5 ${numeric[ci] ? "text-right tabular-nums" : ""} ${v === null ? "text-muted" : ""}`}>
                    {formatCell(v, columns[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <nav aria-label="Table pages" className="mt-2 flex items-center justify-end gap-3 text-sm text-muted">
          <button type="button" className="hover:text-ink disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>
            Page {page + 1} of {pages}
          </span>
          <button type="button" className="hover:text-ink disabled:opacity-40" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </nav>
      )}
    </div>
  );
}
