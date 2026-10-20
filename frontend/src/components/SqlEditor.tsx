"use client";

import { sql, PostgreSQL } from "@codemirror/lang-sql";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import dynamic from "next/dynamic";

const CodeMirror = dynamic(() => import("@uiw/react-codemirror"), {
  ssr: false,
  loading: () => <pre className="min-h-16 p-3 font-mono text-[13px] text-muted">Loading editor…</pre>,
});

const theme = EditorView.theme({
  "&": { backgroundColor: "transparent", fontSize: "13px" },
  ".cm-content": { fontFamily: "var(--font-mono)", caretColor: "var(--ink)", color: "var(--ink)" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none", color: "var(--muted)" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "color-mix(in srgb, var(--accent-soft) 40%, transparent)" },
  "&.cm-focused": { outline: "none" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "var(--accent-soft) !important" },
});

// Token colours come from the palette so they work in light and dark mode.
const highlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: [t.keyword, t.operatorKeyword], color: "var(--accent)", fontWeight: "600" },
    { tag: [t.string, t.special(t.string)], color: "var(--chart-3)" },
    { tag: [t.number, t.bool, t.null], color: "var(--chart-5)" },
    { tag: [t.function(t.variableName), t.standard(t.name)], color: "var(--chart-4)" },
    { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--muted)", fontStyle: "italic" },
    { tag: [t.name, t.variableName, t.propertyName], color: "var(--ink)" },
    { tag: [t.punctuation, t.operator], color: "var(--ink-soft)" },
  ]),
);

export function SqlEditor({
  value,
  onChange,
  onRun,
  label = "SQL query",
}: {
  value: string;
  onChange: (v: string) => void;
  onRun?: () => void;
  label?: string;
}) {
  return (
    <div
      aria-label={label}
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && onRun) {
          e.preventDefault();
          onRun();
        }
      }}
    >
      <CodeMirror
        value={value}
        onChange={onChange}
        extensions={[sql({ dialect: PostgreSQL }), EditorView.lineWrapping, theme, highlight]}
        basicSetup={{ lineNumbers: false, foldGutter: false, highlightActiveLine: true }}
        theme="none"
      />
    </div>
  );
}
