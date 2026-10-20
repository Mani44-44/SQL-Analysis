"use client";

import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TopBar } from "@/components/TopBar";
import { Empty, Notice, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, type EvalRun, type Metrics } from "@/lib/api";
import { humanise, pct, timeAgo } from "@/lib/format";

function isHarnessRun(r: EvalRun) {
  return ["mock", "oracle"].includes(r.config.provider ?? "") || r.model.startsWith("mock");
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-display text-3xl font-semibold tabular-nums tracking-tight">{value}</p>
      <p className="mt-0.5 text-sm text-muted">{label}</p>
    </div>
  );
}

function Bars({ data, label }: { data: { name: string; value: number }[]; label: string }) {
  if (!data.length) return <p className="text-sm text-muted">Nothing recorded.</p>;
  return (
    <div className="h-56" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={150} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <Tooltip contentStyle={{ background: "var(--paper-raised)", border: "1px solid var(--rule)", fontSize: 13 }} />
          <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function MetricsPage() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [showHarness, setShowHarness] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.evalRuns().then(setRuns, (e) => setError(e.message));
    api.metrics(30).then(setMetrics, () => setMetrics(null));
  }, []);

  const visible = useMemo(() => (runs ?? []).filter((r) => showHarness || !isHarnessRun(r)), [runs, showHarness]);
  const current = visible.find((r) => r.id === selected) ?? visible[0];
  const s = current?.summary;

  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto max-w-6xl px-4 py-8 md:px-8">
        <PageHeader title="Accuracy & metrics">
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={showHarness} onChange={(e) => setShowHarness(e.target.checked)} />
            Include harness (mock) runs
          </label>
        </PageHeader>
        {error && <Notice tone="error">{error}</Notice>}

        <section aria-labelledby="bench-h">
          <h2 id="bench-h" className="font-display text-xl font-medium">
            Benchmark
          </h2>
          {runs === null ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-muted">
              <Spinner /> Loading
            </p>
          ) : !current ? (
            <div className="mt-3">
              <Empty title="No benchmark runs yet">
                Run <code className="font-mono">python -m app.eval.run</code> with an API key to score the model on the 91-question finance benchmark.
              </Empty>
            </div>
          ) : (
            <>
              <p className="mt-1 text-sm text-muted">
                {current.dataset}, config {current.config.config ?? "full"}, {current.model}, prompt {current.prompt_version}
                {current.git_sha ? `, commit ${current.git_sha}` : ""}, {timeAgo(current.started_at)}{" "}
                {isHarnessRun(current) && <Pill tone="amber">Harness check, not model accuracy</Pill>}
              </p>
              <div className="mt-6 grid grid-cols-2 gap-8 md:grid-cols-4">
                <Stat value={pct(s?.accuracy)} label={`Overall (95% CI ${pct(s?.accuracy_ci95?.[0], 0)}–${pct(s?.accuracy_ci95?.[1], 0)})`} />
                <Stat value={pct(s?.execution_accuracy)} label="Execution accuracy" />
                <Stat value={pct(s?.self_correction_recovery_rate)} label="Recovered by self-correction" />
                <Stat value={pct(s?.kind_accuracy)} label="Clarify / unanswerable handled" />
              </div>
              <div className="mt-10 grid gap-10 md:grid-cols-2">
                <div>
                  <h3 className="font-medium">Accuracy by question type</h3>
                  <Bars
                    label="Accuracy by tag"
                    data={Object.entries(s?.by_tag ?? {}).map(([k, v]) => ({ name: humanise(k), value: Math.round(v.accuracy * 1000) / 10 }))}
                  />
                </div>
                <div>
                  <h3 className="font-medium">Why answers were wrong</h3>
                  <Bars label="Failure categories" data={Object.entries(s?.error_categories ?? {}).map(([k, v]) => ({ name: humanise(k), value: v }))} />
                </div>
              </div>
              <h3 className="mt-10 font-medium">All runs</h3>
              <div className="mt-2 overflow-x-auto">
                <table className="ledger w-full text-sm">
                  <thead>
                    <tr className="border-b-2 border-rule text-left">
                      <th scope="col" className="px-2 py-2 font-medium">When</th>
                      <th scope="col" className="px-2 py-2 font-medium">Config</th>
                      <th scope="col" className="px-2 py-2 font-medium">Model</th>
                      <th scope="col" className="px-2 py-2 text-right font-medium">Accuracy</th>
                      <th scope="col" className="px-2 py-2 text-right font-medium">First attempt</th>
                      <th scope="col" className="px-2 py-2 text-right font-medium">Cost / case</th>
                      <th scope="col" className="px-2 py-2 text-right font-medium">p50 latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((r) => (
                      <tr key={r.id} className={r.id === current.id ? "bg-accent-soft/50" : ""}>
                        <td className="px-2 py-1.5">
                          <button type="button" className="underline-offset-2 hover:underline" onClick={() => setSelected(r.id)}>
                            {timeAgo(r.started_at)}
                          </button>
                        </td>
                        <td className="px-2 py-1.5">{r.config.config ?? "full"}</td>
                        <td className="px-2 py-1.5">{r.model}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{pct(r.summary.accuracy)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{pct(r.summary.first_attempt_accuracy)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">${(r.summary.cost_usd_per_case ?? 0).toFixed(4)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{r.summary.latency_ms_p50 ?? 0} ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>

        <section aria-labelledby="ops-h" className="mt-14 border-t border-rule pt-8">
          <h2 id="ops-h" className="font-display text-xl font-medium">
            Live usage, last 30 days
          </h2>
          {metrics === undefined ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-muted">
              <Spinner /> Loading
            </p>
          ) : metrics === null ? (
            <p className="mt-3 text-sm text-muted">Usage metrics are not available.</p>
          ) : metrics.total_queries === 0 ? (
            <p className="mt-3 text-sm text-muted">No questions asked in this period.</p>
          ) : (
            <>
              <div className="mt-6 grid grid-cols-2 gap-8 md:grid-cols-5">
                <Stat value={metrics.total_queries.toLocaleString("en-IN")} label="Questions" />
                <Stat value={pct(metrics.success_rate)} label="Answered with a result" />
                <Stat value={`${(metrics.latency_ms_p50 / 1000).toFixed(1)} s`} label={`Median time (p95 ${(metrics.latency_ms_p95 / 1000).toFixed(1)} s)`} />
                <Stat value={`$${metrics.cost_usd_per_query.toFixed(4)}`} label="Cost per question" />
                <Stat value={pct(metrics.thumbs_down_rate)} label={`Marked wrong (${metrics.feedback_count} ratings)`} />
              </div>
              <div className="mt-8 grid gap-10 md:grid-cols-2">
                <div>
                  <h3 className="font-medium">Questions per day</h3>
                  <Bars label="Questions per day" data={Object.entries(metrics.queries_per_day).map(([k, v]) => ({ name: k, value: v }))} />
                </div>
                <div>
                  <h3 className="font-medium">Errors by category</h3>
                  <Bars label="Error categories" data={Object.entries(metrics.failure_categories).map(([k, v]) => ({ name: humanise(k), value: v }))} />
                </div>
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
