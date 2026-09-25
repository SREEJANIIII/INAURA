/**
 * One plain sentence for a failed request, for showing to a student.
 *
 * The API's raw errors ("API error 422 Unprocessable Entity: {"detail":[…]}") are for the
 * console, not the page. This keeps what the server said when it was written for people —
 * "File too large. Max 10 MB" — and otherwise says what happened in the app's own voice.
 * `fallback` is what went wrong in this particular place, e.g. "Your project couldn't be saved."
 *
 * Recognises the API client's ApiError by its shape rather than importing it, so this stays
 * free of the network code and can be tested on its own.
 */

type ApiErrorLike = { name: "ApiError"; status: number; detail: string | null };

const isApiError = (error: unknown): error is ApiErrorLike =>
  error instanceof Error && error.name === "ApiError" && typeof (error as Partial<ApiErrorLike>).status === "number";

/** Server explanations that read as developer notes, not as something a student can act on */
const TECHNICAL = /supabase|table|sql|column|relation|traceback|exception|\.py\b|postgrest|run backend|pgrst|violates|constraint|null value/i;

export function friendlyError(error: unknown, fallback: string): string {
  if (!isApiError(error)) {
    // A cancelled request, or something thrown by our own code: nothing worth reading out
    return fallback;
  }
  const detail = error.detail?.trim() || null;
  const readable = detail && detail.length <= 180 && !TECHNICAL.test(detail) ? detail : null;

  switch (true) {
    case error.status === 0:
      return "INAURA can't be reached right now. Check your connection and try again.";
    case error.status === 401:
      return "Your session has expired. Log in again to carry on.";
    case error.status === 403:
      return "You don't have access to that.";
    case error.status === 413:
      return "That file is too large. The limit is 10 MB.";
    case error.status === 429:
      return "That's a lot of requests at once. Wait a moment and try again.";
    case error.status >= 500:
      return fallback;
    default:
      // 400, 404, 409, 422: the server's reason is usually the most useful thing to say
      return readable ? sentence(readable) : fallback;
  }
}

/** Capitalised, with a full stop, so a server fragment reads like the rest of the page */
function sentence(text: string) {
  const t = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

/** The HTTP status of a failed request (0 when unreachable), or null for anything else */
export const statusOf = (error: unknown): number | null => (isApiError(error) ? error.status : null);
