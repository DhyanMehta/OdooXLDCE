import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "../services/api";
import type { ClubContext, Me } from "../types/api";

type AuthState = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
  activeClub: ClubContext | null;
  setActiveClubId: (clubId: string) => void;
  hasPermission: (permission: string) => boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeClubId, setActiveClubId] = useState<string | null>(
    localStorage.getItem("campusos.activeClubId"),
  );

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<Me>("/api/v1/auth/me");
      setMe(data);
      setActiveClubId((current) => current ?? data.clubs[0]?.club.id ?? null);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (activeClubId) localStorage.setItem("campusos.activeClubId", activeClubId);
  }, [activeClubId]);

  const activeClub = useMemo(() => {
    if (!me) return null;
    return me.clubs.find((c) => c.club.id === activeClubId) ?? me.clubs[0] ?? null;
  }, [me, activeClubId]);

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      refresh,
      login: async (email, password) => {
        const data = await api.post<Me>("/api/v1/auth/login", { email, password });
        setMe(data);
      },
      register: async (email, password, fullName) => {
        const data = await api.post<Me>("/api/v1/auth/register", {
          email,
          password,
          full_name: fullName,
        });
        setMe(data);
      },
      logout: async () => {
        await api.post("/api/v1/auth/logout");
        setMe(null);
      },
      activeClub,
      setActiveClubId: (clubId: string) => setActiveClubId(clubId),
      hasPermission: (permission: string) =>
        Boolean(activeClub?.permissions.includes(permission)),
    }),
    [me, loading, refresh, activeClub],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
