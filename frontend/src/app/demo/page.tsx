"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Notice, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function DemoRedirect() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.demoWorkspace().then((ws) => router.replace(`/w/${ws.id}/ask`), (e) => setError(e.message));
  }, [router]);
  return (
    <main className="mx-auto max-w-xl px-4 py-20">
      {error ? (
        <Notice tone="error" title="The demo workspace isn't set up">
          {error}. Run <code className="font-mono">python -m app.demo.seed</code> in the backend.
        </Notice>
      ) : (
        <p className="flex items-center gap-2 text-muted">
          <Spinner /> Opening the demo
        </p>
      )}
    </main>
  );
}
