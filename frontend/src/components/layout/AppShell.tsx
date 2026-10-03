import { Link, NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../../hooks/useAuth";
import { ADMIN_NAV, PRIMARY_NAV } from "../../lib/nav";
import { initials, roleTitle } from "../../lib/roles";

export function AppShell() {
  const { me, loading, logout, activeClub, setActiveClubId, hasPermission } = useAuth();

  const primary = PRIMARY_NAV.filter((item) => {
    if (item.auth) return Boolean(me);
    // Staff manage the club; membership purchase is for ordinary buyers.
    if (item.to === "/memberships" && activeClub && activeClub.permissions.length > 0) {
      return false;
    }
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
  ];
  const isStaff = staffPerms.some((p) => hasPermission(p));
  const adminItems = ADMIN_NAV.filter((item) => {
    if (item.to === "/admin") return isStaff;
    return Boolean(item.permission && hasPermission(item.permission));
  });

  const displayRole = activeClub ? roleTitle(activeClub.permissions) : "Guest";

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <Link to="/" className="brand sidebar__brand">
          CampusOS
        </Link>

        {me ? (
          <div className="profile-block">
            <div className="avatar" aria-hidden="true">
              {initials(me.user.full_name)}
            </div>
            <div className="profile-block__text">
              <strong>{me.user.full_name}</strong>
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

        {me && activeClub && me.clubs.length > 0 && (
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
          {primary.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {item.label}
            </NavLink>
          ))}

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
