import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as
  | string
  | undefined;

// Helpful runtime warning for missing env — never throw in production build, just warn
if (!supabaseUrl || !supabaseAnonKey) {
  console.warn(
    "[INAURA] Supabase env not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env"
  );
}

// Create client only if configured; otherwise provide a dummy that will error on use
// This keeps build passing without env, but auth flows will show friendly message
export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null;

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

export type OAuthProvider = "google" | "github";

/** Whether Google/GitHub sign-in is switched on in the Supabase dashboard.
    Supabase sends people to a raw error page for a provider that's off, so check first. */
export async function isProviderEnabled(provider: OAuthProvider): Promise<boolean> {
  if (!supabaseUrl || !supabaseAnonKey) return false;
  try {
    const res = await fetch(`${supabaseUrl.replace(/\/$/, "")}/auth/v1/settings`, {
      headers: { apikey: supabaseAnonKey },
    });
    const settings = (await res.json()) as { external?: Record<string, boolean> };
    return !!settings.external?.[provider];
  } catch {
    // Can't tell; let Supabase decide
    return true;
  }
}
