import { useAuth } from "./useAuth";

/**
 * Authenticated club context only — no hardcoded tech-club fallback.
 * Public pages should use the club id/slug from the route instead.
 */
export function useClubId(): string | null {
  const { activeClub } = useAuth();
  return activeClub?.club.id ?? null;
}

export function useActiveClubSlug(): string | null {
  const { activeClub } = useAuth();
  return activeClub?.club.slug ?? null;
}
