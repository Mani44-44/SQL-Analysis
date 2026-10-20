"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useWorkspace } from "@/components/WorkspaceShell";
import { Empty, Notice, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, type ConversationDetail, type ConversationSummary, type SavedQuery } from "@/lib/api";
import { timeAgo } from "@/lib/format";

export default function HistoryPage() {
  const ws = useWorkspace();
  const [convs, setConvs] = useState<ConversationSummary[] | null>(null);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [open, setOpen] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.conversations(ws.id).then(setConvs, (e) => setError(e.message));
    api.savedQueries(ws.id).then(setSaved, () => setSaved([]));
  }, [ws.id]);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="History" />
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="conv-h">
          <h2 id="conv-h" className="font-display text-lg font-medium">
            Conversations
          </h2>
          {convs === null ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-muted">
              <Spinner /> Loading
            </p>
          ) : convs.length === 0 ? (
            <div className="mt-3">
              <Empty title="No questions asked yet" action={<Link href={`/w/${ws.id}/ask`} className="text-accent underline">Ask your first question</Link>} />
            </div>
          ) : (
            <ul className="mt-3 divide-y divide-rule-soft border-y border-rule-soft">
              {convs.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    aria-expanded={open?.id === c.id}
                    className="flex w-full items-baseline gap-3 py-2.5 text-left hover:text-accent"
                    onClick={() => (open?.id === c.id ? setOpen(null) : api.conversation(c.id).then(setOpen, (e) => setError(e.message)))}
                  >
                    <span className="min-w-0 flex-1 truncate font-medium">{c.title || "Untitled"}</span>
                    <span className="shrink-0 text-sm text-muted">
                      {c.turns} {c.turns === 1 ? "question" : "questions"}, {timeAgo(c.last_activity ?? c.created_at)}
                    </span>
                  </button>
                  {open?.id === c.id && (
                    <div className="mb-4 space-y-4 border-l-2 border-accent pl-4">
                      {open.runs.map((r) => (
                        <div key={r.id} className="text-sm">
                          <p className="font-medium">
                            {r.question ?? "Manual SQL"}{" "}
                            {r.status !== "ok" && <Pill tone={r.status === "error" ? "stamp" : "amber"}>{r.status}</Pill>}
                            {r.rating === 1 && <Pill tone="accent">Marked right</Pill>}
                            {r.rating === -1 && <Pill tone="stamp">Marked wrong</Pill>}
                          </p>
                          {r.explanation && <p className="mt-0.5 text-ink-soft">{r.explanation}</p>}
                          {r.sql && <pre className="mt-1 overflow-x-auto rounded bg-raised p-2 font-mono text-xs text-ink-soft">{r.sql}</pre>}
                        </div>
                      ))}
                      <Link href={`/w/${ws.id}/ask?c=${open.id}`} className="inline-block text-sm text-accent underline">
                        Continue this conversation
                      </Link>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="saved-h">
          <h2 id="saved-h" className="font-display text-lg font-medium">
            Saved queries
          </h2>
          {saved.length === 0 ? (
            <p className="mt-3 text-sm text-muted">{ws.is_demo ? "Saving queries is turned off in the demo." : "Save a query from any answer's “Show your work” panel."}</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {saved.map((s) => (
                <li key={s.id} className="rounded-md border border-rule bg-raised p-3 text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{s.title}</span>
                    <button type="button" className="text-xs text-stamp hover:underline" onClick={() => api.deleteSaved(s.id).then(() => setSaved(saved.filter((x) => x.id !== s.id)))}>
                      Delete
                    </button>
                  </div>
                  <pre className="mt-1 max-h-32 overflow-auto font-mono text-xs text-ink-soft">{s.sql}</pre>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
