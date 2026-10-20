"use client";

import { forwardRef } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell as PieCell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Cell, ChartSpec } from "@/lib/api";
import { formatCell, formatCompact, formatNumber, humanise } from "@/lib/format";

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];
const AXIS = { stroke: "var(--muted)", fontSize: 12 };

type Row = Record<string, Cell>;

function toRows(columns: string[], rows: Cell[][]): Row[] {
  return rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i]])));
}

/** Pivot long data (x, series, y) into wide rows keyed by series value. */
function pivot(rows: Row[], x: string, series: string, y: string): { data: Row[]; keys: string[] } {
  const keys: string[] = [];
  const byX = new Map<string, Row>();
  for (const r of rows) {
    const k = String(r[series] ?? "—");
    if (!keys.includes(k)) keys.push(k);
    const xv = String(r[x]);
    const row = byX.get(xv) ?? { [x]: r[x] };
    row[k] = r[y];
    byX.set(xv, row);
  }
  return { data: [...byX.values()], keys };
}

function label(spec: ChartSpec, col: string) {
  return spec.labels?.[col] ?? humanise(col);
}

export const ChartView = forwardRef<HTMLDivElement, { spec: ChartSpec; columns: string[]; rows: Cell[][] }>(
  function ChartView({ spec, columns, rows }, ref) {
    if (spec.type === "table" || !rows.length) return null;
    const data = toRows(columns, rows);

    if (spec.type === "kpi") {
      return (
        <div ref={ref} className="flex flex-wrap gap-8 py-2">
          {spec.y.map((c) => (
            <div key={c}>
              <p className="font-display text-4xl font-semibold tracking-tight tabular-nums">{formatCell(data[0][c], c)}</p>
              <p className="mt-1 text-sm text-muted">{label(spec, c)}</p>
            </div>
          ))}
        </div>
      );
    }

    const x = spec.x as string;
    const yFirst = spec.y[0];
    const tooltip = (
      <Tooltip
        contentStyle={{ background: "var(--paper-raised)", border: "1px solid var(--rule)", borderRadius: 6, fontSize: 13 }}
        labelFormatter={(v) => formatCell(v as Cell, x)}
        formatter={(v, name) => [formatNumber(Number(v), String(name)), String(name)]}
      />
    );
    const xAxis = <XAxis dataKey={x} tick={AXIS} tickFormatter={(v) => formatCell(v as Cell, x)} minTickGap={16} />;
    const yAxis = <YAxis tick={AXIS} width={64} tickFormatter={(v) => formatCompact(Number(v), yFirst)} />;
    const grid = <CartesianGrid stroke="var(--rule-soft)" vertical={false} />;

    let chart: React.ReactElement;
    if (spec.type === "pie") {
      chart = (
        <PieChart>
          <Pie data={data} dataKey={yFirst} nameKey={x} innerRadius="45%" outerRadius="80%" paddingAngle={1} stroke="var(--paper)">
            {data.map((_, i) => (
              <PieCell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          {tooltip}
          <Legend wrapperStyle={{ fontSize: 13 }} />
        </PieChart>
      );
    } else if (spec.type === "scatter") {
      chart = (
        <ScatterChart>
          {grid}
          <XAxis dataKey={x} type="number" tick={AXIS} name={label(spec, x)} tickFormatter={(v) => formatCompact(Number(v), x)} />
          {yAxis}
          {tooltip}
          <Scatter data={data} dataKey={yFirst} fill={COLORS[0]} />
        </ScatterChart>
      );
    } else {
      const { data: wide, keys } = spec.series ? pivot(data, x, spec.series, yFirst) : { data, keys: spec.y };
      const Chart = spec.type === "line" ? LineChart : BarChart;
      chart = (
        <Chart data={wide}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {keys.length > 1 && <Legend wrapperStyle={{ fontSize: 13 }} />}
          {keys.map((k, i) =>
            spec.type === "line" ? (
              <Line key={k} type="monotone" dataKey={k} name={spec.series ? k : label(spec, k)} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={wide.length <= 24} />
            ) : (
              <Bar key={k} dataKey={k} name={spec.series ? k : label(spec, k)} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
            ),
          )}
        </Chart>
      );
    }
    return (
      <div ref={ref} className="h-72 w-full" role="img" aria-label={`${spec.type} chart of ${spec.y.map((c) => label(spec, c)).join(", ")}${spec.x ? ` by ${label(spec, spec.x)}` : ""}`}>
        <ResponsiveContainer width="100%" height="100%">
          {chart}
        </ResponsiveContainer>
      </div>
    );
  },
);
