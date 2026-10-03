export function roleTitle(permissions: string[]): string {
  if (permissions.includes("manage_roles")) return "Club administrator";
  if (permissions.includes("manage_members") || permissions.includes("confirm_dues")) {
    return "Membership manager";
  }
  if (permissions.includes("manage_events") || permissions.includes("check_in")) {
    return "Event organizer";
  }
  if (permissions.includes("manage_announcements") || permissions.includes("manage_mailing_list")) {
    return "Communications officer";
  }
  return "Member";
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export function prettyRoleCode(code: string | null | undefined): string {
  if (!code) return "—";
  return code.replaceAll("_", " ");
}
