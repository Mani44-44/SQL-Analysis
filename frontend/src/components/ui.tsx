"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "quiet" | "danger";

export function Button({
  variant = "quiet",
  className = "",
  busy = false,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-ink hover:brightness-110 disabled:opacity-50",
    quiet: "border border-rule text-ink hover:bg-raised disabled:opacity-50",
    danger: "border border-stamp/50 text-stamp hover:bg-stamp-soft disabled:opacity-50",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-[filter,background-color] ${styles[variant]} ${className}`}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "quiet", className = "" }: { href: string; children: ReactNode; variant?: Variant; className?: string }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-ink hover:brightness-110",
    quiet: "border border-rule text-ink hover:bg-raised",
    danger: "border border-stamp/50 text-stamp",
  };
  return (
    <Link href={href} className={`inline-flex items-center justify-center rounded-md px-4 py-2.5 text-sm font-medium ${styles[variant]} ${className}`}>
      {children}
    </Link>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none ${className}`}
    />
  );
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "error" | "warn"; title?: string; children?: ReactNode }) {
  const styles = {
    info: "border-accent/40 bg-accent-soft text-ink",
    error: "border-stamp/40 bg-stamp-soft text-ink",
    warn: "border-amber/40 bg-amber-soft text-ink",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-md border px-3.5 py-2.5 text-sm ${styles[tone]}`}>
      {title && <p className="font-medium">{title}</p>}
      {children && <div className={title ? "mt-0.5 text-ink-soft" : ""}>{children}</div>}
    </div>
  );
}

export function Pill({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "accent" | "stamp" | "amber" }) {
  const styles = {
    plain: "border-rule text-ink-soft",
    accent: "border-accent/40 text-accent",
    stamp: "border-stamp/40 text-stamp",
    amber: "border-amber/40 text-amber",
  };
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${styles[tone]}`}>{children}</span>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule px-6 py-10 text-center">
      <p className="font-display text-lg">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
      {children}
    </header>
  );
}
