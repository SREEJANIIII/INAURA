import { supabase } from "../lib/supabase";

/**
 * INAURA API client
 * Base URL from VITE_API_URL env, fallback to FastAPI dev server.
 */

export const API_BASE_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8000/api/v1";

type ApiOptions = RequestInit & {
  // Allow query params helper if needed later
  params?: Record<string, string | number | boolean>;
};

/**
 * A request the API answered with an error, or couldn't be reached at all (status 0).
 *
 * The message keeps the "API error 401 Unauthorized: …" form older callers match on;
 * `status` and `detail` are there so new code doesn't have to parse it back out.
 */
export class ApiError extends Error {
  readonly status: number;
  /** The server's own explanation, when it gave a readable one */
  readonly detail: string | null;

  constructor(status: number, statusText: string, body = "") {
    super(status === 0 ? `Network error: ${statusText}` : `API error ${status} ${statusText}${body ? `: ${body}` : ""}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = readDetail(body);
  }
}

/** FastAPI puts its reason in `detail`: a sentence, or a list of validation problems */
function readDetail(body: string): string | null {
  if (!body) return null;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg.replace(/^Value error,\s*/i, "");
    }
  } catch {
    // Not JSON — a proxy's HTML error page, say. Nothing worth showing.
  }
  return null;
}

const isAbort = (err: unknown) => err instanceof DOMException && err.name === "AbortError";

async function fetchWithFallback(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (err) {
    // A cancelled request stays cancelled; retrying it elsewhere would undo the cancel
    if (isAbort(err)) throw err;
    // Local development only: the API may answer on the other of localhost / 127.0.0.1,
    // or only through Vite's proxy
    if (url.startsWith("/api/v1")) {
      try {
        return await fetch(`http://localhost:8000${url}`, init);
      } catch {
        return await fetch(`http://127.0.0.1:8000${url}`, init);
      }
    }
    if (url.includes("localhost:8000/api/v1")) {
      const relUrl = url.replace("http://localhost:8000/api/v1", "/api/v1");
      try {
        return await fetch(relUrl, init);
      } catch {
        const ipUrl = url.replace("http://localhost:8000/api/v1", "http://127.0.0.1:8000/api/v1");
        return await fetch(ipUrl, init);
      }
    }
    if (url.includes("127.0.0.1:8000/api/v1")) {
      const relUrl = url.replace("http://127.0.0.1:8000/api/v1", "/api/v1");
      try {
        return await fetch(relUrl, init);
      } catch {
        const lhUrl = url.replace("http://127.0.0.1:8000/api/v1", "http://localhost:8000/api/v1");
        return await fetch(lhUrl, init);
      }
    }
    throw err;
  }
}

function buildUrl(endpoint: string, params?: ApiOptions["params"]) {
  let url = `${API_BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  if (params) {
    const search = new URLSearchParams(
      Object.entries(params).reduce(
        (acc, [k, v]) => ({ ...acc, [k]: String(v) }),
        {} as Record<string, string>
      )
    ).toString();
    if (search) url += `?${search}`;
  }
  return url;
}

/** The signed-in user's Supabase token, when there is one */
async function authHeader(): Promise<Record<string, string>> {
  try {
    if (supabase) {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (token) return { Authorization: `Bearer ${token}` };
    }
  } catch {
    // ignore — unauthenticated request; the API returns the useful error
  }
  return {};
}

/** Sends the request and turns every failure — unreachable or refused — into an ApiError */
async function send(url: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetchWithFallback(url, init);
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError(0, err instanceof Error ? err.message : "request failed");
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
  return response;
}

export async function apiFetch<T>(
  endpoint: string,
  options: ApiOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;
  const isFormData = fetchOptions.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(await authHeader()),
    ...(fetchOptions.headers as Record<string, string> | undefined),
  };
  if (!isFormData) {
    headers["Content-Type"] = (fetchOptions.headers as Record<string, string> | undefined)?.["Content-Type"] || "application/json";
  }

  const response = await send(buildUrl(endpoint, params), { ...fetchOptions, headers });

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function apiFetchBlob(endpoint: string, options: ApiOptions = {}): Promise<Blob> {
  const { params, ...fetchOptions } = options;
  const headers = {
    ...(await authHeader()),
    ...(fetchOptions.headers as Record<string, string> | undefined),
    "Content-Type": "application/json",
  };
  const response = await send(buildUrl(endpoint, params), { ...fetchOptions, headers });
  return response.blob();
}
