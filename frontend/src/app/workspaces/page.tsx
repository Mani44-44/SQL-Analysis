"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { TopBar } from "@/components/TopBar";
import { Button, Notice, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, ApiError, type Workspace } from "@/lib/api";
import { timeAgo } from "@/lib/format";

export default function WorkspacesPage() {
  const router = useRouter();
  const [items, setItems] = useState<Workspace[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    api.workspaces().then(setItems, (e) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login?next=/workspaces");
      else setError(e);
    });
  }, [router]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const ws = await api.createWorkspace(name.trim());
      router.push(`/w/${ws.id}/data`);
    } catch (err) {
      setError(err as ApiError);
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto max-w-3xl px-4 py-8 md:px-8">
        <PageHeader title="Workspaces" />
        {error && (
          <div className="mb-4">
            <Notice tone="error">{error.message}</Notice>
          </div>
        )}
        <form onSubmit={create} className="mb-8 flex gap-2">
          <label htmlFor="ws-name" className="sr-only">
            New workspace name
          </label>
          <input
            id="ws-name"
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New workspace, e.g. “Club budget 2026”"
            className="min-w-0 flex-1 rounded-md border border-rule bg-raised px-3 py-2"
          />
          <Button type="submit" variant="primary" busy={busy}>
            Create workspace
          </Button>
        </form>
        {items === null ? (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner /> Loading
          </p>
        ) : (
          <ul className="divide-y divide-rule-soft border-y border-rule-soft">
            {items.map((w) => (
              <li key={w.id}>
                <Link href={`/w/${w.id}/ask`} className="flex items-baseline gap-3 py-3 hover:text-accent">
                  <span className="font-medium">{w.name}</span>
                  {w.is_demo && <Pill>Demo</Pill>}
                  <span className="ml-auto text-sm text-muted">created {timeAgo(w.created_at)}</span>
                </Link>
              </li>
            ))}
            {items.length === 0 && <li className="py-3 text-sm text-muted">No workspaces yet. Create one above, then upload a file.</li>}
          </ul>
        )}
      </main>
    </div>
  );
}
