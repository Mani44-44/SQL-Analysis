// Typed client for the AskData API (/api/v1). All requests send cookies for auth.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BASE = `${API_URL}/api/v1`;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "include",
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, `Can't reach the AskData API at ${API_URL}. Check that the backend is running.`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ------------------------------------------------------------------ types

export type Workspace = { id: string; name: string; is_demo: boolean; created_at: string; role?: string | null };

export type ColumnCard = {
  id: string;
  name: string;
  type: string;
  sql_type: string;
  description: string | null;
  original_name: string | null;
  null_pct: number;
  distinct_count: number;
  min_value: string | null;
  max_value: string | null;
  top_values: { value: string; count: number }[];
  sample_values: string[];
  type_overridden: boolean;
};
export type TableCard = { id: string; source_id: string; name: string; row_count: number; description: string | null; columns: ColumnCard[] };
export type GlossaryTerm = { id: string; term: string; definition: string };
export type WorkspaceSchema = {
  tables: TableCard[];
  join_hints: { left_table: string; left_column: string; right_table: string; right_column: string }[];
  glossary: GlossaryTerm[];
};
export type Source = {
  id: string;
  workspace_id: string;
  type: string;
  filename: string;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  created_at: string;
  tables: string[];
};

export type ChartSpec = {
  type: "kpi" | "line" | "bar" | "pie" | "scatter" | "table";
  x: string | null;
  y: string[];
  series: string | null;
  title: string;
  x_kind?: string | null;
  labels?: Record<string, string>;
};
export type Attempt = { number: number; sql: string; error: string | null; error_code: string | null };
export type Cell = string | number | boolean | null | Cell[] | { [k: string]: Cell };

export type AskResult = {
  query_run_id: string;
  conversation_id: string | null;
  status: "ok" | "clarify" | "unanswerable" | "error";
  kind: string;
  question: string;
  resolved_question: string;
  sql: string | null;
  columns: string[];
  column_types: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  assumptions: string[];
  reasoning: string;
  confidence: number | null;
  tables_used: string[];
  clarifying_question: string | null;
  missing_data: string | null;
  explanation: string | null;
  chart: ChartSpec | null;
  warnings: string[];
  attempts: Attempt[];
  error: string | null;
  error_code: string | null;
  duration_ms: number;
  cost_usd: number;
  cached: boolean;
};

export type RunSqlResult = {
  query_run_id: string;
  status: "ok" | "error";
  sql: string | null;
  columns: string[];
  column_types: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  chart: ChartSpec | null;
  error: string | null;
  error_code: string | null;
  duration_ms: number;
};

export type RunSummary = {
  id: string;
  question: string | null;
  resolved_question: string | null;
  status: string;
  kind: string;
  source: string;
  sql: string | null;
  explanation: string | null;
  assumptions: string[];
  chart: ChartSpec | null;
  confidence: number | null;
  row_count: number;
  attempts: number;
  duration_ms: number;
  cost_usd: number;
  error: string | null;
  created_at: string;
  rating: number | null;
};
export type ConversationSummary = { id: string; title: string; created_at: string; last_activity: string | null; turns: number };
export type ConversationDetail = { id: string; workspace_id: string; title: string; created_at: string; runs: RunSummary[] };
export type SavedQuery = { id: string; workspace_id: string; title: string; sql: string; created_at: string };

export type EvalSummary = Record<string, unknown> & {
  accuracy?: number;
  accuracy_ci95?: [number, number];
  execution_accuracy?: number;
  kind_accuracy?: number;
  first_attempt_accuracy?: number;
  self_correction_recovery_rate?: number;
  cost_usd_per_case?: number;
  latency_ms_p50?: number;
  latency_ms_p95?: number;
  n_cases?: number;
  error_categories?: Record<string, number>;
  by_tag?: Record<string, { n: number; accuracy: number }>;
};
export type EvalRun = {
  id: string;
  dataset: string;
  git_sha: string | null;
  model: string;
  prompt_version: string;
  config: { config?: string; provider?: string; repeats?: number };
  started_at: string;
  finished_at: string | null;
  summary: EvalSummary;
};
export type Metrics = {
  days: number;
  total_queries: number;
  queries_per_day: Record<string, number>;
  success_rate: number;
  status_breakdown: Record<string, number>;
  latency_ms_p50: number;
  latency_ms_p95: number;
  cost_usd_total: number;
  cost_usd_per_query: number;
  correction_loop_rate: number;
  feedback_count: number;
  thumbs_down_rate: number;
  failure_categories: Record<string, number>;
};
export type User = { id: string; email: string };

// ------------------------------------------------------------------ endpoints

export const api = {
  me: () => request<User>("/auth/me"),
  register: (email: string, password: string) =>
    request<User>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),

  workspaces: () => request<Workspace[]>("/workspaces"),
  demoWorkspace: () => request<Workspace>("/workspaces/demo"),
  workspace: (id: string) => request<Workspace>(`/workspaces/${id}`),
  createWorkspace: (name: string) => request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name }) }),
  deleteWorkspace: (id: string) => request<void>(`/workspaces/${id}`, { method: "DELETE" }),

  sources: (ws: string) => request<Source[]>(`/workspaces/${ws}/sources`),
  source: (id: string) => request<Source>(`/sources/${id}`),
  upload: (ws: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Source>(`/workspaces/${ws}/sources/upload`, { method: "POST", body });
  },
  deleteSource: (id: string) => request<void>(`/sources/${id}`, { method: "DELETE" }),

  schema: (ws: string) => request<WorkspaceSchema>(`/workspaces/${ws}/schema`),
  patchColumn: (id: string, body: { description?: string; type_override?: string; clear_type_override?: boolean }) =>
    request<WorkspaceSchema>(`/columns/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  patchTable: (id: string, description: string) =>
    request<WorkspaceSchema>(`/tables/${id}`, { method: "PATCH", body: JSON.stringify({ description }) }),
  addGlossary: (ws: string, term: string, definition: string) =>
    request<GlossaryTerm>(`/workspaces/${ws}/glossary`, { method: "POST", body: JSON.stringify({ term, definition }) }),
  deleteGlossary: (id: string) => request<void>(`/glossary/${id}`, { method: "DELETE" }),
  suggestions: (ws: string) => request<string[]>(`/workspaces/${ws}/suggestions`),

  runSql: (ws: string, sql: string, conversationId?: string | null) =>
    request<RunSqlResult>(`/workspaces/${ws}/sql/run`, {
      method: "POST",
      body: JSON.stringify({ sql, conversation_id: conversationId ?? null }),
    }),
  conversations: (ws: string) => request<ConversationSummary[]>(`/workspaces/${ws}/conversations`),
  conversation: (id: string) => request<ConversationDetail>(`/conversations/${id}`),
  feedback: (runId: string, rating: 1 | -1, corrected_sql?: string, comment?: string) =>
    request<unknown>(`/query-runs/${runId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ rating, corrected_sql: corrected_sql || null, comment: comment || null }),
    }),
  exportUrl: (runId: string) => `${BASE}/query-runs/${runId}/export?format=csv`,
  savedQueries: (ws: string) => request<SavedQuery[]>(`/workspaces/${ws}/saved-queries`),
  saveQuery: (ws: string, title: string, sql: string) =>
    request<SavedQuery>(`/workspaces/${ws}/saved-queries`, { method: "POST", body: JSON.stringify({ title, sql }) }),
  deleteSaved: (id: string) => request<void>(`/saved-queries/${id}`, { method: "DELETE" }),

  evalRuns: () => request<EvalRun[]>("/eval/runs"),
  metrics: (days = 30) => request<Metrics>(`/metrics?days=${days}`),
};

// ------------------------------------------------------------------ streaming ask (SSE over POST)

export type StreamEvent =
  | { event: "status"; data: { stage: string; attempt?: number } }
  | { event: "sql"; data: { sql: string; attempt: number } }
  | { event: "rows"; data: { columns: string[]; row_count: number; truncated: boolean } }
  | { event: "chart"; data: { chart: ChartSpec } }
  | { event: "explanation"; data: { text: string } }
  | { event: "result"; data: AskResult }
  | { event: "error"; data: { detail: string; status: number } }
  | { event: "done"; data: Record<string, never> };

export async function askStream(
  ws: string,
  question: string,
  conversationId: string | null,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<AskResult> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/workspaces/${ws}/ask`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal,
    });
  } catch {
    throw new ApiError(0, `Can't reach the AskData API at ${API_URL}.`);
  }
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AskResult | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let name = "message";
      const data: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) continue;
      const payload = JSON.parse(data.join("\n"));
      const ev = { event: name, data: payload } as StreamEvent;
      if (ev.event === "result") result = ev.data;
      if (ev.event === "error") throw new ApiError(ev.data.status, ev.data.detail);
      onEvent(ev);
    }
  }
  if (!result) throw new ApiError(500, "The answer stream ended without a result.");
  return result;
}
