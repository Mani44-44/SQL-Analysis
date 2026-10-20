"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AskBox } from "@/components/AskBox";
import { TopBar } from "@/components/TopBar";
import { Notice } from "@/components/ui";
import { api, type EvalRun } from "@/lib/api";
import { pct } from "@/lib/format";

const EXAMPLES = ["How much did I spend each month?", "Which categories went over budget in May 2026?", "What are my top 5 merchants by spend?"];

function isRealRun(r: EvalRun) {
  return !["mock", "oracle"].includes(r.config.provider ?? "") && !r.model.startsWith("mock");
}

export default function Landing() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bench, setBench] = useState<EvalRun | null | undefined>(undefined);

  useEffect(() => {
    api.evalRuns().then(
      (runs) => setBench(runs.find((r) => isRealRun(r) && r.config.config === "full") ?? null),
      () => setBench(null),
    );
  }, []);

  async function go(question: string) {
    setBusy(true);
    setError(null);
    try {
      const demo = await api.demoWorkspace();
      router.push(`/w/${demo.id}/ask${question ? `?q=${encodeURIComponent(question)}` : ""}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const s = bench?.summary;

  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto max-w-6xl px-4 md:px-8">
        <section className="pb-16 pt-10 md:pt-20">
          <h1 className="max-w-4xl font-display text-5xl font-semibold leading-[1.02] tracking-tight md:text-7xl">Ask your bank statement a question.</h1>
          <p className="mt-5 max-w-2xl text-lg text-ink-soft">
            AskData turns plain English into SQL, runs it in a locked-down sandbox, and gives you the table, a chart, and the exact query behind the answer.
          </p>
          <div className="mt-10 max-w-3xl">
            <AskBox value={q} onChange={setQ} onSubmit={() => go(q.trim())} busy={busy} large placeholder={EXAMPLES[0]} />
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted">Try:</span>
              {EXAMPLES.slice(1).map((e) => (
                <button key={e} type="button" onClick={() => go(e)} className="rounded-full border border-rule px-3 py-1 hover:border-accent hover:bg-raised">
                  {e}
                </button>
              ))}
            </div>
            <p className="mt-4 text-sm text-muted">Runs on a demo of 18 months of synthetic bank, card and UPI transactions. No sign-up needed.</p>
            {error && (
              <div className="mt-4">
                <Notice tone="error" title="The demo isn't available right now">
                  {error}
                </Notice>
              </div>
            )}
          </div>
        </section>

        <section aria-label="How it works" className="grid gap-10 border-t border-rule py-12 md:grid-cols-3">
          <div>
            <h2 className="font-display text-xl font-medium">You can check every answer</h2>
            <p className="mt-2 text-ink-soft">
              Each answer shows the SQL it ran, the assumptions it made and how sure it is. Edit the query and run it again, or mark the answer wrong.
            </p>
          </div>
          <div>
            <h2 className="font-display text-xl font-medium">It can only read</h2>
            <p className="mt-2 text-ink-soft">
              Queries are parsed and checked against an allowlist, then run read-only with no file or network access, a timeout and a memory cap. One workspace can never see another.
            </p>
          </div>
          <div>
            <h2 className="font-display text-xl font-medium">Accuracy is measured</h2>
            {s ? (
              <p className="mt-2 text-ink-soft">
                On the 91-question finance benchmark, the latest run scores <strong className="text-ink">{pct(s.accuracy)}</strong> overall (95% CI {pct(s.accuracy_ci95?.[0])}–
                {pct(s.accuracy_ci95?.[1])}) with {bench!.model}.{" "}
                <a href="/metrics" className="text-accent underline">
                  See the breakdown
                </a>
              </p>
            ) : (
              <p className="mt-2 text-ink-soft">
                A 91-question benchmark with gold SQL runs in CI, with ablations for each pipeline step.{" "}
                {bench === null && "Model scores will appear here after the first benchmark run with an API key."}
              </p>
            )}
          </div>
        </section>
      </main>
      <footer className="mx-auto max-w-6xl border-t border-rule px-4 py-6 text-sm text-muted md:px-8">
        AskData is an open-source portfolio project. Uploaded data stays in your workspace until you delete it.
      </footer>
    </div>
  );
}
