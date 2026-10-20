"use client";

import { useRef, useState } from "react";
import { api, type AskResult, type Cell, type ChartSpec } from "@/lib/api";
import { exportChartPng } from "@/lib/exportPng";
import { pct } from "@/lib/format";
import { ChartView } from "./ChartView";
import { ResultTable } from "./ResultTable";
import { SqlEditor } from "./SqlEditor";
import { Button, Notice, Pill } from "./ui";

type View = {
  runId: string;
  status: AskResult["status"];
  columns: string[];
  rows: Cell[][];
  truncated: boolean;
  chart: ChartSpec | null;
  error: string | null;
};

const STAGE_TEXT: Record<string, string> = {
  generating: "Writing SQL",
  correcting: "Fixing the SQL after an error",
  checking_empty_result: "Double-checking an empty result",
  cached: "Using a recent answer",
};

export function PendingAnswer({ question, stage, sql }: { question: string; stage: string; sql: string | null }) {
  return (
    <article className="ink-in border-b border-rule pb-8" aria-busy="true">
      <h2 className="font-display text-xl font-medium leading-snug">{question}</h2>
      <p className="mt-3 flex items-center gap-2 text-sm text-muted">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent motion-reduce:animate-none" />
        {STAGE_TEXT[stage] ?? (stage === "rows" ? "Running the query" : "Working")}…
      </p>
      {sql && <pre className="mt-3 overflow-x-auto rounded-md bg-raised p-3 font-mono text-[13px] text-ink-soft">{sql}</pre>}
    </article>
  );
}

export function AnswerCard({
  result,
  workspaceId,
  readOnly,
  onAnswerClarification,
}: {
  result: AskResult;
  workspaceId: string;
  readOnly: boolean;
  onAnswerClarification?: (prefix: string) => void;
}) {
  const [view, setView] = useState<View>({
    runId: result.query_run_id,
    status: result.status,
    columns: result.columns,
    rows: result.rows,
    truncated: result.truncated,
    chart: result.chart,
    error: result.error,
  });
  const [sql, setSql] = useState(result.sql ?? "");
  const [running, setRunning] = useState(false);
  const [showTable, setShowTable] = useState(result.chart?.type === "table" || result.chart?.type === "kpi" ? true : result.row_count <= 12);
  const [showWork, setShowWork] = useState(result.status === "error");
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [notice, setNotice] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const edited = sql.trim() !== (result.sql ?? "").trim();

  async function rerun() {
    setRunning(true);
    setNotice(null);
    try {
      const r = await api.runSql(workspaceId, sql, result.conversation_id);
      setView({ runId: r.query_run_id, status: r.status === "ok" ? "ok" : "error", columns: r.columns, rows: r.rows, truncated: r.truncated, chart: r.chart, error: r.error });
      if (r.status === "ok") setShowTable(true);
    } catch (e) {
      setNotice({ tone: "error", text: (e as Error).message });
    } finally {
      setRunning(false);
    }
  }

  async function sendFeedback(value: 1 | -1, withDetails = false) {
    try {
      await api.feedback(result.query_run_id, value, withDetails && edited ? sql : undefined, withDetails ? comment : undefined);
      setRating(value);
      setFeedbackOpen(false);
      setNotice({ tone: "info", text: value === 1 ? "Thanks — marked as helpful." : "Thanks — your correction was saved for review." });
    } catch (e) {
      setNotice({ tone: "error", text: (e as Error).message });
    }
  }

  async function saveQuery() {
    const title = window.prompt("Name this query", result.question.slice(0, 80));
    if (!title) return;
    try {
      await api.saveQuery(workspaceId, title, sql);
      setNotice({ tone: "info", text: `Saved “${title}”.` });
    } catch (e) {
      setNotice({ tone: "error", text: (e as Error).message });
    }
  }

  const readAs = result.resolved_question && result.resolved_question.trim().toLowerCase() !== result.question.trim().toLowerCase();

  return (
    <article className="ink-in border-b border-rule pb-8">
      <h2 className="font-display text-xl font-medium leading-snug">{result.question}</h2>
      {readAs && <p className="mt-1 text-sm text-muted">Read as: {result.resolved_question}</p>}

      {result.status === "clarify" && (
        <div className="mt-4 rounded-md border-l-4 border-accent bg-accent-soft/60 px-4 py-3">
          <p className="font-medium">{result.clarifying_question}</p>
          {onAnswerClarification && (
            <button type="button" className="mt-1 text-sm text-accent underline-offset-2 hover:underline" onClick={() => onAnswerClarification(`${result.question} — `)}>
              Answer in the box below
            </button>
          )}
        </div>
      )}

      {result.status === "unanswerable" && (
        <div className="mt-4">
          <Notice tone="warn" title="This data can't answer that question">
            {result.missing_data}
          </Notice>
        </div>
      )}

      {view.status === "error" && (
        <div className="mt-4">
          <Notice tone="error" title="The query didn't run">
            {view.error ?? result.error}
          </Notice>
        </div>
      )}

      {view.status === "ok" && (
        <>
          {result.explanation && view.runId === result.query_run_id && <p className="mt-3 max-w-[70ch] text-[15px] leading-relaxed">{result.explanation}</p>}

          {(result.warnings.length > 0 || result.assumptions.length > 0) && view.runId === result.query_run_id && (
            <ul className="mt-3 flex flex-wrap gap-2" aria-label="Warnings and assumptions">
              {result.warnings.map((w) => (
                <li key={w}>
                  <Pill tone="amber">{w}</Pill>
                </li>
              ))}
              {result.assumptions.map((a) => (
                <li key={a}>
                  <Pill>Assumed: {a}</Pill>
                </li>
              ))}
            </ul>
          )}

          {view.chart && view.chart.type !== "table" && (
            <div className="mt-5">
              <ChartView ref={chartRef} spec={view.chart} columns={view.columns} rows={view.rows} />
            </div>
          )}

          <div className="mt-4">
            <button type="button" aria-expanded={showTable} className="text-sm font-medium text-accent hover:underline" onClick={() => setShowTable(!showTable)}>
              {showTable ? "Hide table" : `Show table (${view.rows.length.toLocaleString("en-IN")}${view.truncated ? "+" : ""} rows)`}
            </button>
            {showTable && (
              <div className="mt-2">
                <ResultTable columns={view.columns} rows={view.rows} />
              </div>
            )}
          </div>
        </>
      )}

      {(result.sql || result.attempts.length > 0) && (
        <div className="mt-5 rounded-md border border-rule bg-raised">
          <button
            type="button"
            aria-expanded={showWork}
            onClick={() => setShowWork(!showWork)}
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium"
          >
            <span>Show your work</span>
            <span className="text-xs font-normal text-muted">
              {result.attempts.length > 1 ? `${result.attempts.length} attempts · ` : ""}
              {result.confidence !== null ? `confidence ${pct(result.confidence, 0)} · ` : ""}
              {(result.duration_ms / 1000).toFixed(1)} s{result.cached ? " · cached" : ""}
            </span>
          </button>
          {showWork && (
            <div className="border-t border-rule px-3 pb-3">
              {result.reasoning && <p className="pt-3 text-sm text-ink-soft">{result.reasoning}</p>}
              <div className="mt-3 rounded border border-rule-soft bg-paper">
                <SqlEditor value={sql} onChange={setSql} onRun={rerun} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button variant="primary" onClick={rerun} busy={running} disabled={!sql.trim()}>
                  Run SQL
                </Button>
                {!readOnly && (
                  <Button onClick={saveQuery} disabled={!sql.trim()}>
                    Save query
                  </Button>
                )}
                <span className="text-xs text-muted">Ctrl/⌘ + Enter runs. Edited SQL goes through the same safety checks.</span>
              </div>
              {result.tables_used.length > 0 && <p className="mt-3 text-xs text-muted">Tables: {result.tables_used.join(", ")}</p>}
              {result.attempts.length > 1 && (
                <details className="mt-2 text-xs text-muted">
                  <summary className="cursor-pointer">Earlier attempts</summary>
                  <ol className="mt-1 space-y-2">
                    {result.attempts.slice(0, -1).map((a) => (
                      <li key={a.number}>
                        <pre className="overflow-x-auto font-mono">{a.sql}</pre>
                        <p className="text-stamp">{a.error}</p>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          )}
        </div>
      )}

      <footer className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {view.status === "ok" && view.rows.length > 0 && (
          <>
            <a className="rounded-md border border-rule px-3 py-1.5 hover:bg-raised" href={api.exportUrl(view.runId)} download>
              Download CSV
            </a>
            {view.chart && !["table", "kpi"].includes(view.chart.type) && (
              <button
                type="button"
                className="rounded-md border border-rule px-3 py-1.5 hover:bg-raised"
                onClick={() => exportChartPng(chartRef.current, `askdata-${view.runId.slice(0, 8)}.png`).catch((e) => setNotice({ tone: "error", text: e.message }))}
              >
                Download chart
              </button>
            )}
          </>
        )}
        <span className="ml-auto flex items-center gap-1" role="group" aria-label="Was this answer right?">
          <span className="mr-1 text-muted">Right answer?</span>
          <button type="button" aria-pressed={rating === 1} className={`rounded-md border px-2.5 py-1 ${rating === 1 ? "border-accent bg-accent-soft" : "border-rule hover:bg-raised"}`} onClick={() => sendFeedback(1)}>
            Yes
          </button>
          <button type="button" aria-pressed={rating === -1} className={`rounded-md border px-2.5 py-1 ${rating === -1 ? "border-stamp bg-stamp-soft" : "border-rule hover:bg-raised"}`} onClick={() => setFeedbackOpen(!feedbackOpen)}>
            No
          </button>
        </span>
      </footer>

      {feedbackOpen && (
        <form
          className="mt-3 rounded-md border border-rule p-3"
          onSubmit={(e) => {
            e.preventDefault();
            sendFeedback(-1, true);
          }}
        >
          <label htmlFor={`fb-${result.query_run_id}`} className="text-sm font-medium">
            What was wrong?
          </label>
          <textarea id={`fb-${result.query_run_id}`} value={comment} onChange={(e) => setComment(e.target.value)} rows={2} className="mt-1 w-full rounded border border-rule bg-paper p-2 text-sm" />
          <p className="mt-1 text-xs text-muted">{edited ? "Your edited SQL will be attached as the correction." : "Tip: fix the SQL under “Show your work” and it will be attached as the correction."}</p>
          <div className="mt-2 flex gap-2">
            <Button type="submit" variant="primary">
              Send feedback
            </Button>
            <Button type="button" onClick={() => setFeedbackOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {notice && (
        <div className="mt-3">
          <Notice tone={notice.tone}>{notice.text}</Notice>
        </div>
      )}
    </article>
  );
}
