/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase, isSupabaseConfigured, isProviderEnabled, type OAuthProvider } from "../lib/supabase";
import { clearPageData } from "../lib/pageData";
import { resetRoleSync } from "../lib/roleSync";

type AuthState = {
  user: User | null;
  session: Session | null;
  loading: boolean;
  isConfigured: boolean;
  signUp: (email: string, password: string) => Promise<{ error: string | null }>;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  /** Google/GitHub sign-in: leaves the page for the provider, then comes back signed in */
  signInWithProvider: (provider: OAuthProvider) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
  resetPassword: (email: string) => Promise<{ error: string | null }>;
  /** Sets a new password for whoever is signed in — including by a reset link */
  updatePassword: (password: string) => Promise<{ error: string | null }>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isSupabaseConfigured || !supabase) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session ?? null);
      setUser(data.session?.user ?? null);
      setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((event, sess) => {
      // Never show one account's remembered page data to another
      if (event === "SIGNED_OUT") {
        clearPageData();
        resetRoleSync();
      }
      setSession(sess);
      setUser(sess?.user ?? null);
      setLoading(false);
    });

    return () => sub.subscription.unsubscribe();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      session,
      loading,
      isConfigured: isSupabaseConfigured,
      signUp: async (email, password) => {
        if (!supabase) return { error: "Supabase not configured" };
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) return { error: error.message };
        return { error: null };
      },
      signIn: async (email, password) => {
        if (!supabase) return { error: "Supabase not configured" };
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) return { error: error.message };
        return { error: null };
      },
      signInWithProvider: async (provider) => {
        if (!supabase) return { error: "Supabase not configured" };
        const name = provider === "google" ? "Google" : "GitHub";
        if (!(await isProviderEnabled(provider))) {
          return { error: `${name} sign-in isn't switched on yet. Please use your email for now.` };
        }
        const { error } = await supabase.auth.signInWithOAuth({
          provider,
          // New accounts land on profile setup from here; existing ones on their career track
          options: { redirectTo: `${window.location.origin}/career-track` },
        });
        if (error) return { error: error.message };
        return { error: null };
      },
      signOut: async () => {
        clearPageData();
        resetRoleSync();
        if (supabase) await supabase.auth.signOut();
      },
      resetPassword: async (email) => {
        if (!supabase) return { error: "Supabase not configured" };
        // The emailed link signs them in on the reset page, where they choose a new password
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/reset-password`,
        });
        if (error) return { error: error.message };
        return { error: null };
      },
      updatePassword: async (password) => {
        if (!supabase) return { error: "Supabase not configured" };
        const { error } = await supabase.auth.updateUser({ password });
        if (error) return { error: error.message };
        return { error: null };
      },
    }),
    [user, session, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
