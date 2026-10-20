"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type User } from "@/lib/api";
import { Brand } from "./WorkspaceShell";

export function TopBar() {
  const router = useRouter();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => {
    api.me().then(setUser, () => setUser(null));
  }, []);

  async function signOut() {
    await api.logout().catch(() => undefined);
    setUser(null);
    router.push("/");
  }
  return (
    <header className="mx-auto flex max-w-6xl items-center gap-5 px-4 py-4 md:px-8">
      <Brand />
      <nav aria-label="Main" className="ml-auto flex items-center gap-5 text-sm">
        <Link href="/metrics" className="text-ink-soft hover:text-ink">
          Accuracy
        </Link>
        {user ? (
          <>
            <Link href="/workspaces" className="text-ink-soft hover:text-ink">
              Your workspaces
            </Link>
            <button type="button" onClick={signOut} className="text-ink-soft hover:text-ink" title={user.email}>
              Sign out
            </button>
          </>
        ) : user === null ? (
          <>
            <Link href="/login" className="text-ink-soft hover:text-ink">
              Sign in
            </Link>
            <Link href="/register" className="rounded-md border border-rule px-3 py-1.5 hover:bg-raised">
              Create account
            </Link>
          </>
        ) : null}
      </nav>
    </header>
  );
}
