import { Link, NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../../hooks/useAuth";
import { ADMIN_NAV, PRIMARY_NAV } from "../../lib/nav";
import { initials, roleTitle } from "../../lib/roles";

function withClubQuery(path: string, clubId: string | null): string {
  if (!clubId) return path;
  if (
    path === "/events" ||
    path === "/memberships" ||
    path === "/announcements" ||
    path === "/shop" ||
    path === "/projects" ||
    path === "/expenses" ||
    path === "/orders" ||
    path === "/tickets" ||
    path === "/my-merch" ||
    path === "/my-assignments" ||
    path === "/my-refunds"
  ) {
    return `${path}?club=${clubId}`;
  }
  return path;
}

export function AppShell() {
  const { me, loading, logout, activeClub, setActiveClubId, hasPermission } = useAuth();
  const activeClubId = activeClub?.club.id ?? null;
  const activeSlug = activeClub?.club.slug ?? null;

  const primary = PRIMARY_NAV.filter((item) => {
    if (item.auth) return Boolean(me);
    return true;
  });

  const staffPerms = [
    "manage_roles",
    "manage_events",
    "manage_announcements",
    "manage_mailing_list",
    "manage_members",
    "manage_plans",
    "check_in",
    "view_audit",
    "confirm_dues",
    "manage_merchandise",
    "fulfill_merchandise",
    "manage_projects",
    "review_expenses",
    "record_reimbursement",
    "record_refunds",
    "view_finance",
    "manage_budgets",
  ];
  const isStaff = staffPerms.some((p) => hasPermission(p));
  const adminItems = ADMIN_NAV.filter((item) => {
    if (item.to === "/admin") return isStaff;
    if (item.anyPermission?.length) {
      return item.anyPermission.some((p) => hasPermission(p));
    }
    return Boolean(item.permission && hasPermission(item.permission));
  });

  const displayRole = activeClub ? roleTitle(activeClub.permissions) : "Guest";

  function resolveNavTo(to: string): string {
    if (to === "/clubs") {
      return activeSlug ? `/clubs/${activeSlug}` : "/clubs";
    }
    return withClubQuery(to, activeClubId);
  }

  return (
    <div className="app-frame">
      <aside className="sidebar sidebar--overflow">
        <Link to="/" className="brand sidebar__brand">
          CampusOS
        </Link>

        {me ? (
          <div className="profile-block">
            <Link to="/profile" className="avatar" aria-label="Profile">
              {initials(me.user.full_name)}
            </Link>
            <div className="profile-block__text">
              <Link to="/profile">
                <strong>{me.user.full_name}</strong>
              </Link>
              <span>{displayRole}</span>
            </div>
          </div>
        ) : (
          <div className="profile-block profile-block--guest">
            <div className="avatar avatar--muted" aria-hidden="true">
              ?
            </div>
            <div className="profile-block__text">
              <strong>Guest</strong>
              <span>Browse publicly</span>
            </div>
          </div>
        )}

        {me && me.clubs.length > 0 && activeClub && (
          <label className="sidebar__club">
            Club
            <select
              aria-label="Active club"
              value={activeClub.club.id}
              onChange={(e) => setActiveClubId(e.target.value)}
            >
              {me.clubs.map((c) => (
                <option key={c.club.id} value={c.club.id}>
                  {c.club.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <nav className="side-nav">
          <p className="side-nav__label">Browse</p>
          {primary.map((item) => {
            const href = resolveNavTo(item.to);
            return (
              <NavLink
                key={item.to}
                to={href}
                className={({ isActive }) => (isActive ? "active" : undefined)}
              >
                {item.to === "/clubs" ? (activeSlug ? "Club" : "Clubs") : item.label}
              </NavLink>
            );
          })}

          {adminItems.length > 0 && (
            <>
              <p className="side-nav__label">Admin</p>
              {adminItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => (isActive ? "active" : undefined)}
                >
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="sidebar__footer">
          {loading ? null : me ? (
            <button type="button" className="btn btn--ghost" onClick={() => void logout()}>
              Log out
            </button>
          ) : (
            <Link className="btn" to="/login">
              Log in
            </Link>
          )}
        </div>
      </aside>

      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
