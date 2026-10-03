import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { clubKey, invalidate } from "../lib/queryCache";
import { api, ApiError } from "../services/api";
import type { ClubContext, Me } from "../types/api";

type AuthState = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<Me | null>;
  login: (email: string, password: string) => Promise<Me>;
  register: (email: string, password: string, fullName: string) => Promise<Me>;
  logout: () => Promise<void>;
  updateProfile: (body: {
    full_name?: string;
    email?: string;
    current_password?: string;
    new_password?: string;
  }) => Promise<Me>;
  activeClub: ClubContext | null;
  setActiveClubId: (clubId: string) => void;
  hasPermission: (permission: string) => boolean;
  /** Permissions for a specific club (e.g. event's club), not the sidebar selection. */
  hasPermissionForClub: (clubId: string, permission: string) => boolean;
  clubContext: (clubId: string) => ClubContext | null;
};

const AuthContext = createContext<AuthState | null>(null);
const ACTIVE_KEY = "campusos.activeClubId";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeClubId, setActiveClubIdState] = useState<string | null>(() =>
    localStorage.getItem(ACTIVE_KEY),
  );

  const refresh = useCallback(async () => {
    try {
      const data = await api.get("/api/v1/auth/me");
      setMe(data);
      setActiveClubIdState((current) => {
        if (current && data.clubs.some((c) => c.club.id === current)) return current;
        return data.clubs[0]?.club.id ?? null;
      });
      return data;
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setMe(null);
      } else {
        setMe(null);
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (activeClubId) localStorage.setItem(ACTIVE_KEY, activeClubId);
  }, [activeClubId]);

  const setActiveClubId = useCallback((clubId: string) => {
    setActiveClubIdState((prev) => {
      if (prev && prev !== clubId) {
        invalidate(clubKey(prev, "*"), clubKey(clubId, "*"), "me");
      }
      return clubId;
    });
  }, []);

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
        const data = await api.post("/api/v1/auth/login", { body: { email, password } });
        setMe(data);
        setActiveClubIdState((current) => {
          if (current && data.clubs.some((c) => c.club.id === current)) return current;
          return data.clubs[0]?.club.id ?? null;
        });
        invalidate("me");
        return data;
      },
      register: async (email, password, fullName) => {
        const data = await api.post("/api/v1/auth/register", {
          body: { email, password, full_name: fullName },
        });
        setMe(data);
        setActiveClubIdState(data.clubs[0]?.club.id ?? null);
        invalidate("me");
        return data;
      },
      logout: async () => {
        try {
          await api.post("/api/v1/auth/logout");
        } catch {
          /* session may already be gone */
        }
        setMe(null);
        invalidate("me");
      },
      updateProfile: async (body) => {
        const data = await api.patch("/api/v1/auth/me", { body });
        setMe(data);
        invalidate("me");
        return data;
      },
      activeClub,
      setActiveClubId,
      hasPermission: (permission: string) =>
        Boolean(activeClub?.permissions.includes(permission)),
      hasPermissionForClub: (clubId: string, permission: string) => {
        const ctx = me?.clubs.find((c) => c.club.id === clubId);
        return Boolean(ctx?.permissions.includes(permission));
      },
      clubContext: (clubId: string) => me?.clubs.find((c) => c.club.id === clubId) ?? null,
    }),
    [me, loading, refresh, activeClub, setActiveClubId],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
