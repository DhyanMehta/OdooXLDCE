export type NavItem = {
  to: string;
  label: string;
  permission?: string;
  public?: boolean;
  auth?: boolean;
  admin?: boolean;
};

/** Primary navigation — always compact. */
export const PRIMARY_NAV: NavItem[] = [
  { to: "/clubs/tech-club", label: "Club", public: true },
  { to: "/events", label: "Events", public: true },
  { to: "/announcements", label: "Announcements", public: true },
  { to: "/memberships", label: "Memberships", public: true },
  { to: "/home", label: "Home", auth: true },
  { to: "/tickets", label: "My tickets", auth: true },
];

/** Admin tools — shown in a single Admin menu, never dumped into the top bar. */
export const ADMIN_NAV: NavItem[] = [
  { to: "/admin", label: "Admin home", admin: true },
  { to: "/admin/plans", label: "Plans", permission: "manage_plans", admin: true },
  { to: "/admin/members", label: "Members", permission: "manage_members", admin: true },
  { to: "/admin/events", label: "Events", permission: "manage_events", admin: true },
  { to: "/admin/check-in", label: "Check-in", permission: "check_in", admin: true },
  { to: "/admin/announcements", label: "Announcements", permission: "manage_announcements", admin: true },
  { to: "/admin/mailing-list", label: "Mailing list", permission: "manage_mailing_list", admin: true },
  { to: "/admin/roles", label: "Roles", permission: "manage_roles", admin: true },
  { to: "/admin/audit", label: "Audit", permission: "view_audit", admin: true },
];

/** @deprecated use PRIMARY_NAV / ADMIN_NAV */
export const NAV_ITEMS = [...PRIMARY_NAV, ...ADMIN_NAV];
