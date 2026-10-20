"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { TopBar } from "./TopBar";
import { Button, Notice } from "./ui";

// Only same-site paths are allowed as a post-login destination (no open redirects).
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/workspaces";
  return raw;
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLogin = mode === "login";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isLogin ? api.login(email.trim(), password) : api.register(email.trim(), password));
      router.replace(next);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 401
          ? "That email and password don't match an account."
          : status === 409
            ? "An account with this email already exists. Sign in instead."
            : status === 422
              ? "Enter a valid email and a password of at least 8 characters."
              : status === 429
                ? "Too many attempts. Wait a minute and try again."
                : (err as Error).message,
      );
      setBusy(false);
    }
  }

  const other = isLogin ? "/register" : "/login";
  const otherHref = next === "/workspaces" ? other : `${other}?next=${encodeURIComponent(next)}`;

  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto max-w-sm px-4 py-12">
        <h1 className="font-display text-3xl font-semibold tracking-tight">{isLogin ? "Sign in" : "Create an account"}</h1>
        <p className="mt-2 text-sm text-ink-soft">
          {isLogin
            ? "Open your workspaces and saved questions."
            : "Upload your own spreadsheets into private workspaces. The demo stays open without an account."}
        </p>
        <form onSubmit={submit} className="mt-8 space-y-4">
          {error && <Notice tone="error">{error}</Notice>}
          <div>
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-rule bg-raised px-3 py-2"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              maxLength={128}
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-rule bg-raised px-3 py-2"
            />
            {!isLogin && <p className="mt-1 text-xs text-muted">At least 8 characters.</p>}
          </div>
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            {isLogin ? "Sign in" : "Create account"}
          </Button>
        </form>
        <p className="mt-6 text-sm text-ink-soft">
          {isLogin ? "New here? " : "Already have an account? "}
          <Link href={otherHref} className="text-accent underline-offset-2 hover:underline">
            {isLogin ? "Create an account" : "Sign in"}
          </Link>
        </p>
      </main>
    </div>
  );
}
