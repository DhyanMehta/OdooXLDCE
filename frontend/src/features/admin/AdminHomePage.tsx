import { Link } from "react-router-dom";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { ADMIN_NAV } from "../../lib/nav";

const DESCRIPTIONS: Record<string, string> = {
  "/admin/plans": "Create and edit membership plans and dues.",
  "/admin/members": "View affiliations and paid membership state.",
  "/admin/dues": "Confirm offline membership payments.",
  "/admin/events": "Create, publish, and cancel events.",
  "/admin/check-in": "Check in attendees with ticket tokens.",
  "/admin/announcements": "Draft, publish, and see delivery status.",
  "/admin/mailing-list": "View subscribers, add emails, unsubscribe people.",
  "/admin/roles": "Assign roles, handover leadership, view history.",
  "/admin/audit": "Review important club changes.",
  "/admin/merchandise": "Catalog, inventory, and order fulfillment.",
  "/admin/projects": "Volunteer projects, tasks, and rosters.",
  "/admin/expenses": "Review expense claims and record reimbursements.",
  "/admin/refunds": "Approve and complete manual refund payouts.",
  "/admin/finance": "Income, spending, balances, and budgets.",
};

function navItemVisible(
  item: (typeof ADMIN_NAV)[number],
  hasPermission: (code: string) => boolean,
): boolean {
  if (!item.permission && !item.anyPermission?.length) return false;
  if (item.anyPermission?.length) {
    return item.anyPermission.some((p) => hasPermission(p));
  }
  return Boolean(item.permission && hasPermission(item.permission));
}

function prettyPermission(code: string): string {
  return code.replaceAll("_", " ");
}

export function AdminHomePage() {
  const { me, activeClub, hasPermission } = useAuth();

  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/admin">log in</Link>.
      </Feedback>
    );
  }
  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;

  const tools = ADMIN_NAV.filter(
    (item) => item.to !== "/admin" && navItemVisible(item, hasPermission),
  );

  if (tools.length === 0) {
    return (
      <Feedback tone="danger">You do not have administrative permissions in this club.</Feedback>
    );
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Admin · {activeClub.club.name}</h1>
        <p className="muted">Staff tools for this club.</p>
      </div>
      <section className="panel stack">
        <h2>Your permissions</h2>
        <div className="chip-row">
          {activeClub.permissions.map((p) => (
            <span key={p} className="badge">
              {prettyPermission(p)}
            </span>
          ))}
        </div>
      </section>
      <section className="grid-2">
        {tools.map((tool) => (
          <Link key={tool.to} to={tool.to} className="panel stack admin-card">
            <h2>{tool.label === "Check-in" ? "Check-in" : tool.label}</h2>
            <p className="muted">{DESCRIPTIONS[tool.to] ?? "Open tool"}</p>
          </Link>
        ))}
      </section>
    </div>
  );
}
