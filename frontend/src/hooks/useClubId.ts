import { useEffect, useState } from "react";

import { api } from "../services/api";
import type { ClubContext } from "../types/api";
import { useAuth } from "./useAuth";

/** Prefer auth active club; otherwise resolve public tech-club for browsing. */
export function useClubId(): { clubId: string | null; clubName: string | null; loading: boolean } {
  const { activeClub } = useAuth();
  const [fallback, setFallback] = useState<ClubContext | null>(null);
  const [loading, setLoading] = useState(!activeClub);

  useEffect(() => {
    if (activeClub) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    api
      .get<ClubContext>("/api/v1/clubs/by-slug/tech-club")
      .then((ctx) => {
        if (!cancelled) setFallback(ctx);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeClub]);

  const club = activeClub ?? fallback;
  return { clubId: club?.club.id ?? null, clubName: club?.club.name ?? null, loading };
}
