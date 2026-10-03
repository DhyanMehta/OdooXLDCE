export type NavItem = {
  to: string;
  label: string;
  permission?: string;
  /** Show when the user has any of these permissions (admin nav). */
  anyPermission?: string[];
  public?: boolean;
  auth?: boolean;
  admin?: boolean;
};

/** Primary navigation — club links are resolved dynamically in AppShell. */
export const PRIMARY_NAV: NavItem[] = [
  { to: "/clubs", label: "Clubs", public: true },
  { to: "/events", label: "Events", public: true },
  { to: "/announcements", label: "Announcements", public: true },
  { to: "/memberships", label: "Memberships", public: true },
  { to: "/shop", label: "Shop", public: true },
  { to: "/projects", label: "Projects", public: true },
  { to: "/home", label: "Home", auth: true },
  { to: "/tickets", label: "My tickets", auth: true },
  { to: "/orders", label: "Orders", auth: true },
  { to: "/my-merch", label: "My merch", auth: true },
  { to: "/my-assignments", label: "My volunteering", auth: true },
  { to: "/expenses", label: "Expenses", auth: true },
  { to: "/my-refunds", label: "My refunds", auth: true },
  { to: "/profile", label: "Profile", auth: true },
];

export const ADMIN_NAV: NavItem[] = [
  { to: "/admin", label: "Admin home", admin: true },
  { to: "/admin/plans", label: "Plans", permission: "manage_plans", admin: true },
  { to: "/admin/members", label: "Members", permission: "manage_members", admin: true },
  { to: "/admin/dues", label: "Pending dues", permission: "confirm_dues", admin: true },
  { to: "/admin/events", label: "Events", permission: "manage_events", admin: true },
  { to: "/admin/check-in", label: "Check-in", permission: "check_in", admin: true },
  { to: "/admin/announcements", label: "Announcements", permission: "manage_announcements", admin: true },
  { to: "/admin/mailing-list", label: "Mailing list", permission: "manage_mailing_list", admin: true },
  { to: "/admin/roles", label: "Roles", permission: "manage_roles", admin: true },
  { to: "/admin/audit", label: "Audit", permission: "view_audit", admin: true },
  {
    to: "/admin/merchandise",
    label: "Merchandise",
    anyPermission: ["manage_merchandise", "fulfill_merchandise"],
    admin: true,
  },
  { to: "/admin/projects", label: "Projects", permission: "manage_projects", admin: true },
  {
    to: "/admin/expenses",
    label: "Expense review",
    anyPermission: ["review_expenses", "record_reimbursement"],
    admin: true,
  },
  { to: "/admin/refunds", label: "Refunds", permission: "record_refunds", admin: true },
  { to: "/admin/finance", label: "Finance", permission: "view_finance", admin: true },
];
