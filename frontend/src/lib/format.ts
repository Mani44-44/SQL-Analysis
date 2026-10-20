import type { Cell } from "./api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const money = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact =new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

const MONEY_HINT = /(amount|spend|spent|budget|balance|income|total|cost|price|over_by|limit|salary|net|refund)/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(T00:00:00(\.0+)?)?$/;
const ISO_TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

export function isMoneyColumn(name: string): boolean {
  return MONEY_HINT.test(name);
}

export function formatNumber(v: number, column = ""): string {
  if (!Number.isFinite(v)) return String(v);
  if (isMoneyColumn(column)) return `₹${Number.isInteger(v) ? inr.format(v) : money.format(v)}`;
  if (Math.abs(v) < 1 && v !== 0) return v.toLocaleString("en-IN", { maximumSignificantDigits: 3 });
  return inr.format(v);
}

export function formatCompact(v: number, column = ""): string {
  return `${isMoneyColumn(column) ? "₹" : ""}${compact.format(v)}`;
}

export function formatDate(s: string): string {
  const d = new Date(ISO_DATE.test(s) ? `${s.slice(0, 10)}T00:00:00` : s);
  if (Number.isNaN(d.getTime())) return s;
  if (s.slice(8, 10) === "01" && ISO_DATE.test(s)) {
    return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  }
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatCell(v: Cell, column = ""): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return formatNumber(v, column);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string") {
    if (ISO_DATE.test(v)) return formatDate(v);
    if (ISO_TS.test(v)) return new Date(v).toLocaleString("en-IN");
    return v;
  }
  return JSON.stringify(v);
}

export function humanise(name: string): string {
  const s = name.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function timeAgo(iso: string): string {
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return new Date(then).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function pct(v: number | undefined | null, digits = 1): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  return `${(100 * v).toFixed(digits)}%`;
}
