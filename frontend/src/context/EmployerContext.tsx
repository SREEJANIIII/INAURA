import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useAuth } from "./AuthContext";
import {
  listEmployers,
  createEmployer as apiCreateEmployer,
  listMembers,
  listRequirements,
  type Employer,
  type Member,
  type Requirement,
} from "../services/employers";

type EmployerContextType = {
  employers: Employer[];
  currentEmployer: Employer | null;
  setCurrentEmployer: (employer: Employer | null) => void;
  members: Member[];
  requirements: Requirement[];
  loading: boolean;
  hasEmployerAccess: boolean;
  isOwner: boolean;
  error: string | null;
  refreshEmployers: () => Promise<Employer[]>;
  refreshRequirements: () => Promise<Requirement[]>;
  refreshMembers: () => Promise<Member[]>;
  createEmployerOrg: (payload: {
    name: string;
    description?: string | null;
    industry?: string | null;
    website?: string | null;
    location?: string | null;
    contact_email?: string | null;
  }) => Promise<Employer>;
};

const EmployerContext = createContext<EmployerContextType | undefined>(undefined);

const STORAGE_KEY = "inaura_active_employer_id";

export function EmployerProvider({ children }: { children: ReactNode }) {
  const { user, isConfigured } = useAuth();
  const [employers, setEmployers] = useState<Employer[]>([]);
  const [currentEmployer, setCurrentEmployerState] = useState<Employer | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const hasEmployerAccess = useMemo(() => {
    if (!user) return false;
    if (employers.length > 0) return true;
    if (user.user_metadata?.role === "employer") return true;
    return false;
  }, [user, employers.length]);

  const refreshEmployers = useCallback(async (): Promise<Employer[]> => {
    if (!user || !isConfigured) {
      setEmployers([]);
      setCurrentEmployerState(null);
      setLoading(false);
      return [];
    }
    setError(null);
    try {
      const rows = await listEmployers();
      setEmployers(rows);
      const savedId = localStorage.getItem(STORAGE_KEY);
      const matched = rows.find((r) => r.id === savedId);
      if (matched) {
        setCurrentEmployerState(matched);
      } else if (rows.length > 0) {
        setCurrentEmployerState(rows[0]);
        localStorage.setItem(STORAGE_KEY, rows[0].id);
      } else {
        setCurrentEmployerState(null);
        localStorage.removeItem(STORAGE_KEY);
      }
      return rows;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // If 404 or empty, user might not have employer membership yet
      setError(msg);
      setEmployers([]);
      setCurrentEmployerState(null);
      return [];
    } finally {
      setLoading(false);
    }
  }, [user, isConfigured]);

  const setCurrentEmployer = useCallback((emp: Employer | null) => {
    setCurrentEmployerState(emp);
    if (emp) {
      localStorage.setItem(STORAGE_KEY, emp.id);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const refreshMembers = useCallback(async (): Promise<Member[]> => {
    if (!currentEmployer) {
      setMembers([]);
      return [];
    }
    try {
      const rows = await listMembers(currentEmployer.id);
      setMembers(rows);
      return rows;
    } catch {
      setMembers([]);
      return [];
    }
  }, [currentEmployer]);

  const refreshRequirements = useCallback(async (): Promise<Requirement[]> => {
    if (!currentEmployer) {
      setRequirements([]);
      return [];
    }
    try {
      const rows = await listRequirements(currentEmployer.id);
      setRequirements(rows);
      return rows;
    } catch {
      setRequirements([]);
      return [];
    }
  }, [currentEmployer]);

  useEffect(() => {
    void refreshEmployers();
  }, [refreshEmployers]);

  useEffect(() => {
    if (currentEmployer) {
      void refreshMembers();
      void refreshRequirements();
    } else {
      setMembers([]);
      setRequirements([]);
    }
  }, [currentEmployer, refreshMembers, refreshRequirements]);

  const isOwner = useMemo(() => {
    if (!user || !currentEmployer) return false;
    const currentMember = members.find((m) => m.user_id === user.id);
    return currentMember ? currentMember.role === "owner" : false;
  }, [user, currentEmployer, members]);

  const createEmployerOrg = useCallback(
    async (payload: {
      name: string;
      description?: string | null;
      industry?: string | null;
      website?: string | null;
      location?: string | null;
      contact_email?: string | null;
    }): Promise<Employer> => {
      const created = await apiCreateEmployer(payload);
      const updated = await refreshEmployers();
      const newlyCreated = updated.find((e) => e.id === created.id) || created;
      setCurrentEmployer(newlyCreated);
      return newlyCreated;
    },
    [refreshEmployers, setCurrentEmployer]
  );

  const value = useMemo<EmployerContextType>(
    () => ({
      employers,
      currentEmployer,
      setCurrentEmployer,
      members,
      requirements,
      loading,
      hasEmployerAccess,
      isOwner,
      error,
      refreshEmployers,
      refreshRequirements,
      refreshMembers,
      createEmployerOrg,
    }),
    [
      employers,
      currentEmployer,
      setCurrentEmployer,
      members,
      requirements,
      loading,
      hasEmployerAccess,
      isOwner,
      error,
      refreshEmployers,
      refreshRequirements,
      refreshMembers,
      createEmployerOrg,
    ]
  );

  return <EmployerContext.Provider value={value}>{children}</EmployerContext.Provider>;
}

export function useEmployer() {
  const ctx = useContext(EmployerContext);
  if (!ctx) throw new Error("useEmployer must be used within EmployerProvider");
  return ctx;
}
