/**
 * Minimal client for the RagIndex FastAPI backend.
 *
 * By default all calls go to same-origin "/api/..." paths, which the Vite dev
 * server proxies to FastAPI on :8000 (see vite.config.ts) and which also work in
 * production when the API is served from the same origin (or behind a reverse
 * proxy). To point the UI at a backend on a DIFFERENT origin, set
 * VITE_API_BASE_URL at build time, e.g. "https://api.example.com".
 */

// Configured backend origin (empty = same-origin). A trailing slash is trimmed so
// appending "/api/..." never produces a double slash.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

/** Prefix an API path with the configured backend base URL. */
function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export interface BuildResult {
  built: boolean;
  doc_count: number;
  documents: string[];
}

export interface ChatSource {
  doc_id: string;
  doc_name: string;
  url: string | null;
  pages: string;
}

/** The measured signals behind a confidence score (each 0..100). */
export interface ConfidenceDrivers {
  grounding: number;
  focus: number;
  cohesion: number;
  consistency: number;
}

/** An interpretable confidence for one answer (0..100 + verdict + breakdown). */
export interface ChatConfidence {
  score: number;
  verdict: string;
  reason?: string;
  grounded: boolean;
  drivers?: ConfidenceDrivers | null;
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
  confidence?: ChatConfidence | null;
  meta: { docs_indexed: number; sections_used: number };
}

export interface IndexStatus {
  built: boolean;
  doc_count: number;
  documents: { doc_id: string; doc_name: string; url: string | null }[];
  store_path: string;
}

export interface TreeNode {
  name: string;
  kind: "root" | "doc" | "node";
  summary?: string;
  url?: string | null;
  children: TreeNode[];
}

export interface IndexTree extends TreeNode {
  doc_count: number;
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
}

/** Build a multipart form of files, preserving folder-relative paths. */
function filesForm(files: File[]): FormData {
  const form = new FormData();
  for (const file of files) {
    const path =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
      file.name;
    form.append("files", file, path);
  }
  return form;
}

/** Upload a set of files and build the PageIndex index over them (blocking). */
export async function buildIndex(
  files: File[],
  signal?: AbortSignal,
): Promise<BuildResult> {
  const res = await fetch(apiUrl("/api/index/build"), {
    method: "POST",
    body: filesForm(files),
    signal,
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

export interface JobStatus {
  job_id: string;
  status: "running" | "done" | "error";
  progress: { done: number; total: number };
  elapsed: number;
  eta: number | null;
  error: string | null;
  result: BuildResult | null;
}

/** A progress snapshot from the server while a build runs. */
export interface BuildProgress {
  done: number;
  total: number;
  /** Seconds the build has been running (server clock). */
  elapsed: number;
  /** Estimated seconds remaining, or null if not yet known. */
  eta: number | null;
}

/** Start an index build in the background; returns a job id immediately. */
export async function buildIndexAsync(
  files: File[],
  signal?: AbortSignal,
): Promise<{ job_id: string }> {
  const res = await fetch(apiUrl("/api/index/build_async"), {
    method: "POST",
    body: filesForm(files),
    signal,
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Poll the status of a background build job. */
export async function getIndexJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await fetch(
    apiUrl(`/api/index/jobs/${encodeURIComponent(jobId)}`),
    { signal },
  );
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/**
 * Build the index in the background, reporting progress, and resolve with the
 * result. Polls ~every second until the job finishes or errors.
 */
export async function buildIndexWithProgress(
  files: File[],
  onProgress?: (progress: BuildProgress) => void,
  signal?: AbortSignal,
): Promise<BuildResult> {
  const { job_id } = await buildIndexAsync(files, signal);
  for (; ;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const job = await getIndexJob(job_id, signal);
    if (onProgress)
      onProgress({
        done: job.progress.done,
        total: job.progress.total,
        elapsed: job.elapsed ?? 0,
        eta: job.eta ?? null,
      });
    if (job.status === "done") {
      if (!job.result) throw new Error("Build finished but returned no result.");
      return job.result;
    }
    if (job.status === "error") {
      throw new Error(job.error || "The index build failed.");
    }
  }
}

/** Is an index built, and over which documents? */
export async function getIndexStatus(signal?: AbortSignal): Promise<IndexStatus> {
  const res = await fetch(apiUrl("/api/index/status"), { signal });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** The indexed corpus as a nested tree (root -> documents -> sections). */
export async function getIndexTree(signal?: AbortSignal): Promise<IndexTree> {
  const res = await fetch(apiUrl("/api/index/tree"), { signal });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Ask a question over the indexed corpus. */
export async function chat(
  message: string,
  topK = 3,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const res = await fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, top_k: topK }),
    signal,
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Fetch the full index (for packaging a resumable bundle). */
export async function exportStore(
  signal?: AbortSignal,
): Promise<{ store: unknown; doc_count: number }> {
  const res = await fetch(apiUrl("/api/index/export"), { signal });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Restore an index from an imported bundle so chat/tree resume against it. */
export async function importStore(store: unknown): Promise<{ doc_count: number }> {
  const res = await fetch(apiUrl("/api/index/import"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ store }),
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Clear the index so the app starts empty again (chat/tree have nothing until rebuilt). */
export async function resetIndex(
  signal?: AbortSignal,
): Promise<{ built: boolean; doc_count: number }> {
  const res = await fetch(apiUrl("/api/index/reset"), { method: "POST", signal });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}
