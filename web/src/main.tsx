import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import "./styles.css";

type Filter = "needs_review" | "in_progress" | "has_human_evidence" | "all";
type Status =
  | "passed"
  | "partially_passed"
  | "failed"
  | "timed_out"
  | "error"
  | "inconclusive"
  | "skipped";

interface Summary {
  task_id: string;
  conversation_id: string;
  status?: string;
  repository_root?: string;
  prompt_preview?: string;
  models: string[];
  categories: string[];
  router_checks: Record<string, number>;
  human_evidence_count: number;
  needs_review: boolean;
  started_at?: string;
  updated_at?: string;
  finished_at?: string;
}

interface Run {
  status: Status | "running";
  source: "router_verification" | "user_submitted";
  verification_method: string;
  check_type: string;
  command?: string;
  output_excerpt?: string;
  duration_ms?: number;
  commit?: string;
  started_at?: string;
}

interface Generation {
  generation_task_id: string;
  generation_id: string;
  prompt_preview?: string;
  model?: string;
  model_id?: string;
  status?: string;
  classifications: Array<{
    category: string;
    subcategory?: string;
    intent?: string;
    confidence?: number;
    source?: string;
  }>;
  outcome_signals: Array<{ signal_type: string; payload?: Record<string, unknown> }>;
  activity: {
    event_count: number;
    edited_files: string[];
    repository_relative_files: string[];
    commands: string[];
    tool_failures: number;
  };
}

interface Detail {
  task_id: string;
  conversation_id: string;
  task: Record<string, unknown>;
  generations: Generation[];
  outcome_signals: Array<{ signal_type: string; payload?: Record<string, unknown> }>;
  verification_runs: Run[];
  verification_trusted: boolean;
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

function formatDate(value?: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function shortPath(value?: string) {
  if (!value) return "Unknown repository";
  const normalized = value.replaceAll("\\", "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] ?? normalized;
}

function statusLabel(status?: string) {
  return status?.replaceAll("_", " ") ?? "unknown";
}

function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">CR</span>
          <span>Cursor Review</span>
        </Link>
        <span className="topbar-note">local evidence console</span>
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "warning" | "success" | "danger" | "info";
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {action}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">✓</div>
      <h2>{message}</h2>
      <p>New Cursor conversations will appear here after the collector finishes.</p>
    </div>
  );
}

function Inbox() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>(
    (params.get("filter") as Filter) || "needs_review",
  );
  const [rows, setRows] = useState<Summary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api<Summary[]>(`/api/conversations?filter=${filter}`)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    setParams({ filter }, { replace: true });
    return () => {
      cancelled = true;
    };
  }, [filter, setParams]);

  const filters: Array<[Filter, string]> = [
    ["needs_review", "Needs review"],
    ["in_progress", "In progress"],
    ["has_human_evidence", "Reviewed"],
    ["all", "All conversations"],
  ];

  return (
    <>
      <PageHeader
        eyebrow="Review inbox"
        title="Decide what held up"
        description="Cursor stays where work happens. This is where you inspect evidence and add your own verification."
        action={
          <div className="stat-card">
            <strong>{rows.length}</strong>
            <span>{filter === "needs_review" ? "waiting for review" : "visible rows"}</span>
          </div>
        }
      />
      <div className="filter-row">
        {filters.map(([value, label]) => (
          <button
            className={`filter-button ${filter === value ? "active" : ""}`}
            key={value}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {error ? <div className="alert alert-danger">{error}</div> : null}
      {loading ? (
        <div className="loading">Loading conversations…</div>
      ) : rows.length === 0 ? (
        <EmptyState message="Nothing needs attention" />
      ) : (
        <div className="conversation-table">
          <div className="table-header">
            <span>Conversation</span>
            <span>Repository</span>
            <span>Classification</span>
            <span>Router checks</span>
            <span>Human</span>
          </div>
          {rows.map((row) => (
            <Link
              className="table-row"
              key={row.task_id}
              to={`/conversations/${row.task_id}`}
            >
              <div className="conversation-cell">
                <strong>{row.prompt_preview || "No prompt preview"}</strong>
                <small>{formatDate(row.updated_at || row.started_at)}</small>
              </div>
              <span>{shortPath(row.repository_root)}</span>
              <span>
                {row.categories.length ? (
                  <Badge tone="info">{row.categories.join(", ")}</Badge>
                ) : (
                  "Unclassified"
                )}
              </span>
              <span className="check-summary">
                {Object.entries(row.router_checks).length
                  ? Object.entries(row.router_checks).map(([status, count]) => (
                      <Badge key={status} tone={status === "passed" ? "success" : "warning"}>
                        {count} {statusLabel(status)}
                      </Badge>
                    ))
                  : "Pending"}
              </span>
              <span>
                {row.human_evidence_count ? (
                  <Badge tone="success">{row.human_evidence_count} recorded</Badge>
                ) : (
                  <Badge tone="warning">Needed</Badge>
                )}
              </span>
            </Link>
          ))}
        </div>
      )}
      <p className="privacy-note">
        Local-only view. Prompts and tool output are already redacted and bounded by the collector.
      </p>
    </>
  );
}

function EvidenceSection({
  title,
  runs,
  empty,
}: {
  title: string;
  runs: Run[];
  empty: string;
}) {
  return (
    <section className="evidence-section">
      <div className="section-heading">
        <h3>{title}</h3>
        <span>{runs.length}</span>
      </div>
      {runs.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <div className="evidence-list">
          {runs.map((run, index) => (
            <div className="evidence-item" key={`${run.source}-${run.started_at}-${index}`}>
              <div className="evidence-icon">
                {run.status === "passed" ? "✓" : run.status === "failed" ? "!" : "•"}
              </div>
              <div className="evidence-content">
                <div className="evidence-title">
                  <strong>{run.check_type}</strong>
                  <Badge tone={run.status === "passed" ? "success" : run.status === "failed" ? "danger" : "warning"}>
                    {statusLabel(run.status)}
                  </Badge>
                </div>
                <small>{run.command || `${run.verification_method} verification`}</small>
                {run.output_excerpt ? <p>{run.output_excerpt}</p> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ActionPanel({
  detail,
  onSaved,
  onClose,
}: {
  detail: Detail;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"verdict" | "test" | "not_verifiable">("verdict");
  const [status, setStatus] = useState<Status>("passed");
  const [command, setCommand] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      await api(`/api/conversations/${detail.task_id}/verification`, {
        method: "POST",
        body: JSON.stringify({
          status: mode === "not_verifiable" ? "inconclusive" : mode === "test" ? "inconclusive" : status,
          verification_method: mode === "not_verifiable" ? "not_verifiable" : "manual",
          check_type: mode === "not_verifiable" ? "research" : mode === "test" ? "test" : "behavior",
          command,
          output: notes,
          commit: typeof detail.task.repository_commit === "string" ? detail.task.repository_commit : null,
        }),
      });
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not record evidence");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="action-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Append evidence</p>
            <h2>{mode === "verdict" ? "Record a verdict" : mode === "test" ? "Link a test" : "Close as not verifiable"}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="segmented">
          <button className={mode === "verdict" ? "selected" : ""} onClick={() => setMode("verdict")}>Verdict</button>
          <button className={mode === "test" ? "selected" : ""} onClick={() => setMode("test")}>Link test</button>
          <button className={mode === "not_verifiable" ? "selected" : ""} onClick={() => setMode("not_verifiable")}>Not verifiable</button>
        </div>
        {mode === "verdict" ? (
          <label>
            Result
            <select value={status} onChange={(event) => setStatus(event.target.value as Status)}>
              <option value="passed">Passed</option>
              <option value="partially_passed">Partially passed</option>
              <option value="failed">Failed</option>
              <option value="inconclusive">Inconclusive</option>
            </select>
          </label>
        ) : null}
        {mode === "test" ? (
          <label>
            Test path or command
            <input
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder="tests/unit/test_schema.py"
            />
          </label>
        ) : null}
        <label>
          Notes
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={mode === "not_verifiable" ? "Why this turn cannot be checked" : "What did you verify?"}
            rows={4}
          />
        </label>
        {error ? <div className="alert alert-danger">{error}</div> : null}
        <div className="panel-actions">
          <button className="button secondary" onClick={onClose}>Cancel</button>
          <button className="button primary" disabled={saving} onClick={submit}>
            {saving ? "Saving…" : "Append evidence"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ConversationReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});
  const [runningChecks, setRunningChecks] = useState(false);
  const [runMessage, setRunMessage] = useState("");

  const load = () => {
    if (!id) return;
    setLoading(true);
    api<Detail>(`/api/conversations/${id}`)
      .then(setDetail)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const { routerRuns, humanRuns } = useMemo(() => {
    const runs = detail?.verification_runs ?? [];
    return {
      routerRuns: runs.filter((run) => run.source === "router_verification"),
      humanRuns: runs.filter((run) => run.source === "user_submitted"),
    };
  }, [detail]);

  if (loading) return <div className="loading">Loading conversation…</div>;
  if (error || !detail) {
    return (
      <div className="error-page">
        <h1>Could not open conversation</h1>
        <p>{error || "Conversation not found"}</p>
        <Link className="button secondary" to="/">Back to inbox</Link>
      </div>
    );
  }

  const task = detail.task;
  const runChecks = async () => {
    setRunningChecks(true);
    setRunMessage("");
    try {
      const result = await api<{ processed: number }>(`/api/conversations/${detail.task_id}/verification/run`, { method: "POST" });
      setRunMessage(result.processed ? "Checks completed. Refreshing evidence…" : "No checks were configured.");
      load();
    } catch (reason) {
      setRunMessage(reason instanceof Error ? reason.message : "Checks could not run");
    } finally {
      setRunningChecks(false);
    }
  };

  return (
    <>
      <div className="breadcrumb">
        <button onClick={() => navigate(-1)}>← Inbox</button>
        <span>/</span>
        <span>{shortPath(typeof task.repository_root === "string" ? task.repository_root : undefined)}</span>
      </div>
      <div className="review-header">
        <div>
          <p className="eyebrow">Conversation review</p>
          <h1>{detail.generations[0]?.prompt_preview || "Untitled conversation"}</h1>
          <div className="meta-row">
            <Badge tone={task.status === "completed" ? "success" : "warning"}>{statusLabel(String(task.status || "unknown"))}</Badge>
            <span>{shortPath(String(task.repository_root || ""))}</span>
            <span>{String(task.model || task.model_id || "Model unavailable")}</span>
            <span>{formatDate(String(task.finished_at || task.updated_at || ""))}</span>
          </div>
        </div>
        <div className="header-actions">
          {detail.verification_trusted ? (
            <button className="button secondary" disabled={runningChecks} onClick={runChecks}>
              {runningChecks ? "Running checks…" : "Run repo checks"}
            </button>
          ) : null}
          <button
            className="button primary"
            onClick={() => setPanelOpen(true)}
          >
            Add verification
          </button>
        </div>
      </div>
      {runMessage ? <div className="alert alert-info">{runMessage}</div> : null}
      <div className="review-grid">
        <section>
          <div className="section-heading page-section-heading">
            <h2>Generation timeline</h2>
            <span>{detail.generations.length} turns</span>
          </div>
          <div className="timeline">
            {detail.generations.map((generation, index) => (
              <article className="generation-card" key={generation.generation_task_id}>
                <div className="timeline-marker">{index + 1}</div>
                <div className="generation-body">
                  <div className="generation-topline">
                    <strong>Turn {index + 1}</strong>
                    <span>{generation.model || generation.model_id || "Model unavailable"}</span>
                    {generation.classifications.map((classification) => (
                      <Badge key={`${classification.source}-${classification.category}`} tone="info">
                        {classification.category}
                      </Badge>
                    ))}
                  </div>
                  <p className="generation-prompt">{generation.prompt_preview || "Prompt unavailable"}</p>
                  <div className="activity-grid">
                    <div><span>Edited files</span><strong>{generation.activity.edited_files.length}</strong></div>
                    <div><span>Commands</span><strong>{generation.activity.commands.length}</strong></div>
                    <div><span>Tool failures</span><strong className={generation.activity.tool_failures ? "danger-text" : ""}>{generation.activity.tool_failures}</strong></div>
                  </div>
                  {generation.activity.repository_relative_files.length ? (
                    <div className="file-list-control">
                      <button
                        className="file-toggle"
                        aria-expanded={Boolean(expandedFiles[generation.generation_task_id])}
                        onClick={() =>
                          setExpandedFiles((current) => ({
                            ...current,
                            [generation.generation_task_id]: !current[generation.generation_task_id],
                          }))
                        }
                      >
                        {expandedFiles[generation.generation_task_id]
                          ? "Hide edited files"
                          : `Show ${generation.activity.repository_relative_files.length} edited files`}
                      </button>
                      {expandedFiles[generation.generation_task_id] ? (
                        <div className="file-list">
                          {generation.activity.repository_relative_files.map((file) => (
                            <code key={file}>{file}</code>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
        <aside className="evidence-column">
          <h2>Evidence stack</h2>
          <EvidenceSection
            title="Router checks"
            runs={routerRuns}
            empty="No router checks recorded."
          />
          <EvidenceSection
            title="Your verification"
            runs={humanRuns}
            empty="Add a verdict, test, or research note."
          />
        </aside>
      </div>
      {panelOpen ? (
        <ActionPanel
          detail={detail}
          onClose={() => setPanelOpen(false)}
          onSaved={() => {
            setPanelOpen(false);
            load();
          }}
        />
      ) : null}
    </>
  );
}

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Inbox />} />
        <Route path="/conversations/:id" element={<ConversationReview />} />
      </Routes>
    </AppShell>
  );
}

export default function Root() {
  return (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<Root />);
