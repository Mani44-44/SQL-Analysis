"use client";

import { useEffect, useRef } from "react";
import { Button } from "./ui";

export function AskBox({
  value,
  onChange,
  onSubmit,
  busy,
  placeholder,
  large = false,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  placeholder: string;
  large?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() && !busy) onSubmit();
      }}
      className="flex items-end gap-2 rounded-xl border-2 border-ink/80 bg-raised p-2 focus-within:border-accent"
    >
      <label htmlFor="ask-input" className="sr-only">
        Ask a question about your data
      </label>
      <textarea
        id="ask-input"
        ref={ref}
        rows={1}
        value={value}
        maxLength={2000}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (value.trim() && !busy) onSubmit();
          }
        }}
        placeholder={placeholder}
        className={`min-w-0 flex-1 resize-none bg-transparent px-2 py-1.5 font-display outline-none placeholder:text-muted ${large ? "text-2xl md:text-3xl" : "text-lg"}`}
      />
      <Button type="submit" variant="primary" busy={busy} disabled={!value.trim()} className={large ? "px-5 py-3 text-base" : ""}>
        Ask
      </Button>
    </form>
  );
}
