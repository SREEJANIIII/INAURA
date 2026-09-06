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
