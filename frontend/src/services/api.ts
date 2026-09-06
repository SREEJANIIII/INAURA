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

export async function apiFetch<T>(
  endpoint: string,
  options: ApiOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;

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

  // Attach Supabase JWT if available
  let authHeader: Record<string, string> = {};
  try {
    if (supabase) {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (token) authHeader = { Authorization: `Bearer ${token}` };
    }
  } catch {
    // ignore — unauthenticated request
  }

  const isFormData = fetchOptions.body instanceof FormData;
  const headers: Record<string, string> = {
    ...authHeader,
    ...(fetchOptions.headers as Record<string, string> | undefined),
  };
  if (!isFormData) {
    headers["Content-Type"] = (fetchOptions.headers as Record<string, string> | undefined)?.["Content-Type"] || "application/json";
  }

  const response = await fetch(url, {
    ...fetchOptions,
    headers,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `API error ${response.status} ${response.statusText}${text ? `: ${text}` : ""}`
    );
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
