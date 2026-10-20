"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type User, type Workspace } from "@/lib/api";
import { Notice, Spinner } from "./ui";

const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const ws = useContext(WorkspaceContext);
  if (!ws) throw new Error("useWorkspace must be used inside WorkspaceShell");
  return ws;
}

export function Brand() {
  return (
    <Link href="/" className="font-display text-lg font-semibold tracking-tight">
      Ask<span className="text-accent">Data</span>
    </Link>
  );
}

export function WorkspaceShell({ id, children }: { id: string; children: ReactNode }) {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.me().then(setUser, () => setUser(null));
  }, []);

  useEffect(() => {
    api.workspace(id).then(setWs, (e) => {
      // Private workspace and nobody signed in: send them to sign in, then back here.
      if (e instanceof ApiError && e.status === 401) router.replace(`/login?next=${encodeURIComponent(`/w/${id}/ask`)}`);
      else setError(e);
    });
  }, [id, router]);

  async function signOut() {
    await api.logout().catch(() => undefined);
    router.push("/");
  }

  const nav = [
    { href: `/w/${id}/ask`, label: "Ask" },
    { href: `/w/${id}/data`, label: "Data" },
    { href: `/w/${id}/history`, label: "History" },
  ];

  return (
    <div className="mx-auto flex min-h-dvh max-w-[1400px] flex-col md:flex-row">
      <aside className="border-b border-rule px-4 py-3 md:sticky md:top-0 md:h-dvh md:w-56 md:shrink-0 md:border-b-0 md:border-r md:px-5 md:py-6">
        <div className="flex items-center justify-between md:block">
          <Brand />
          {ws && (
            <p className="truncate text-sm text-muted md:mt-6" title={ws.name}>
              {ws.name}
            </p>
          )}
        </div>
        <nav aria-label="Workspace" className="mt-3 flex gap-1 md:mt-6 md:flex-col">
          {nav.map((n) => {
            const active = pathname?.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-accent-soft font-medium text-ink" : "text-ink-soft hover:bg-raised"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="hidden md:mt-10 md:block">
          <Link href="/workspaces" className="block py-1 text-sm text-muted hover:text-ink">
            All workspaces
          </Link>
          <Link href="/metrics" className="block py-1 text-sm text-muted hover:text-ink">
            Accuracy & metrics
          </Link>
          {user ? (
            <button type="button" onClick={signOut} className="block py-1 text-sm text-muted hover:text-ink" title={user.email}>
              Sign out
            </button>
          ) : (
            <Link href={`/login?next=${encodeURIComponent(pathname ?? "/")}`} className="block py-1 text-sm text-muted hover:text-ink">
              Sign in
            </Link>
          )}
        </div>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-8">
        {error ? (
          <Notice tone="error" title={error.status === 404 ? "This workspace doesn't exist" : error.status === 401 || error.status === 403 ? "You don't have access to this workspace" : "Couldn't load the workspace"}>
            {error.message} <Link href="/workspaces" className="underline">Go to your workspaces</Link>
          </Notice>
        ) : ws ? (
          <WorkspaceContext.Provider value={ws}>{children}</WorkspaceContext.Provider>
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner /> Loading workspace
          </p>
        )}
      </main>
    </div>
  );
}
