"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AnswerCard, PendingAnswer } from "@/components/AnswerCard";
import { AskBox } from "@/components/AskBox";
import { useWorkspace } from "@/components/WorkspaceShell";
import { Notice } from "@/components/ui";
import { api, askStream, type AskResult } from "@/lib/api";

type Entry =
  | { key: string; kind: "pending"; question: string; stage: string; sql: string | null }
  | { key: string; kind: "done"; result: AskResult }
  | { key: string; kind: "failed"; question: string; message: string };

function AskInner() {
  const ws = useWorkspace();
  const params = useSearchParams();
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(params.get("c"));
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [hasData, setHasData] = useState<boolean | null>(null);
  const busy = entries.some((e) => e.kind === "pending");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.suggestions(ws.id).then(setSuggestions, () => setSuggestions([]));
    api.schema(ws.id).then((s) => setHasData(s.tables.length > 0), () => setHasData(null));
  }, [ws.id]);

  // Resume a conversation from history (?c=...): show its previous answers' text.
  useEffect(() => {
    const c = params.get("c");
    if (!c) return;
    api.conversation(c).then(
      (conv) =>
        setEntries(
          conv.runs
            .filter((r) => r.source === "ask")
            .map((r) => ({
              key: r.id,
              kind: "done" as const,
              result: {
                query_run_id: r.id, conversation_id: conv.id, status: r.status as AskResult["status"], kind: r.kind,
                question: r.question ?? "", resolved_question: r.resolved_question ?? "", sql: r.sql, columns: [],
                column_types: [], rows: [], row_count: r.row_count, truncated: false, assumptions: r.assumptions as string[],
                reasoning: "", confidence: r.confidence, tables_used: [], clarifying_question: r.status === "clarify" ? r.explanation : null,
                missing_data: r.status === "unanswerable" ? r.explanation : null, explanation: r.status === "ok" ? r.explanation : null,
                chart: null, warnings: r.status === "ok" ? ["Re-run the SQL below to see the rows again."] : [], attempts: [],
                error: r.error, error_code: null, duration_ms: r.duration_ms, cost_usd: r.cost_usd, cached: false,
              },
            })),
        ),
      () => undefined,
    );
  }, [params]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries.length]);

  const ask = useCallback(
    async (q: string) => {
      const key = crypto.randomUUID();
      setQuestion("");
      setEntries((prev) => [...prev, { key, kind: "pending", question: q, stage: "generating", sql: null }]);
      const update = (patch: Partial<{ stage: string; sql: string | null }>) =>
        setEntries((prev) => prev.map((e) => (e.key === key && e.kind === "pending" ? { ...e, ...patch } : e)));
      try {
        const result = await askStream(ws.id, q, conversationId, (ev) => {
          if (ev.event === "status") update({ stage: ev.data.stage });
          else if (ev.event === "sql") update({ sql: ev.data.sql, stage: "rows" });
        });
        setConversationId(result.conversation_id);
        setEntries((prev) => prev.map((e) => (e.key === key ? { key, kind: "done", result } : e)));
      } catch (err) {
        setEntries((prev) => prev.map((e) => (e.key === key ? { key, kind: "failed", question: q, message: (err as Error).message } : e)));
      }
    },
    [ws.id, conversationId],
  );

  // A question handed over from the landing page (?q=...) is asked once.
  const autoAsked = useRef(false);
  useEffect(() => {
    const q = params.get("q");
    if (q && !autoAsked.current && !params.get("c")) {
      autoAsked.current = true;
      ask(q);
    }
  }, [params, ask]);

  const empty = entries.length === 0;

  return (
    <div className="mx-auto max-w-3xl">
      {empty && (
        <div className="pt-4 md:pt-10">
          <h1 className="font-display text-3xl font-semibold tracking-tight md:text-4xl">What do you want to know?</h1>
          <p className="mt-2 text-muted">
            {ws.is_demo
              ? "This demo holds 18 months of synthetic bank, card and UPI transactions. Ask in plain English; you'll see the SQL behind every answer."
              : "Ask in plain English. Every answer shows the SQL it ran, so you can check it."}
          </p>
        </div>
      )}

      {hasData === false && (
        <div className="mt-6">
          <Notice tone="info" title="This workspace has no data yet">
            <Link href={`/w/${ws.id}/data`} className="underline">
              Upload a CSV, Excel or SQLite file
            </Link>{" "}
            to start asking questions.
          </Notice>
        </div>
      )}

      <div className="mt-8 space-y-8" aria-live="polite">
        {entries.map((e) =>
          e.kind === "pending" ? (
            <PendingAnswer key={e.key} question={e.question} stage={e.stage} sql={e.sql} />
          ) : e.kind === "failed" ? (
            <article key={e.key} className="border-b border-rule pb-8">
              <h2 className="font-display text-xl font-medium">{e.question}</h2>
              <div className="mt-3">
                <Notice tone="error" title="Couldn't get an answer">
                  {e.message}
                </Notice>
              </div>
            </article>
          ) : (
            <AnswerCard key={e.key} result={e.result} workspaceId={ws.id} readOnly={ws.is_demo} onAnswerClarification={(p) => setQuestion(p)} />
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <div className={`${empty ? "mt-8" : "sticky bottom-0 mt-6 bg-gradient-to-t from-paper from-70% to-transparent pb-4 pt-6"}`}>
        <AskBox
          value={question}
          onChange={setQuestion}
          onSubmit={() => ask(question.trim())}
          busy={busy}
          large={empty}
          placeholder={empty ? "How much did I spend each month?" : "Ask a follow-up, e.g. “now only for UPI”"}
        />
        {empty && suggestions.length > 0 && (
          <div className="mt-5">
            <p className="text-sm text-muted">Try one of these</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => ask(s)} className="rounded-full border border-rule px-3 py-1.5 text-left text-sm hover:border-accent hover:bg-raised">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!empty && (
          <p className="mt-2 text-xs text-muted">
            Follow-ups use this conversation&apos;s context.{" "}
            <button
              type="button"
              className="underline"
              onClick={() => {
                setEntries([]);
                setConversationId(null);
              }}
            >
              Start a new conversation
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense>
      <AskInner />
    </Suspense>
  );
}
