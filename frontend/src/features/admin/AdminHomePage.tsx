import { Link } from "react-router-dom";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { ADMIN_NAV } from "../../lib/nav";

const DESCRIPTIONS: Record<string, string> = {
  "/admin/plans": "Create and edit membership plans and dues.",
  "/admin/members": "View paid memberships and entitlement dates.",
  "/admin/events": "Create, publish, and cancel events.",
  "/admin/check-in": "Scan or enter ticket tokens at the door.",
  "/admin/announcements": "Draft, publish, and see delivery status.",
  "/admin/mailing-list": "View subscribers, add emails, unsubscribe people.",
  "/admin/roles": "Assign roles, handover leadership, view history.",
  "/admin/audit": "Review important club changes.",
};

function prettyPermission(code: string): string {
  return code.replaceAll("_", " ");
}

export function AdminHomePage() {
  const { me, activeClub, hasPermission } = useAuth();

  if (!me) return <Feedback tone="warn">Please <Link to="/login">log in</Link>.</Feedback>;
  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;

  const tools = ADMIN_NAV.filter(
    (item) => item.to !== "/admin" && item.permission && hasPermission(item.permission),
  );

  if (tools.length === 0) {
    return <Feedback tone="danger">You do not have administrative permissions in this club.</Feedback>;
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
            <h2>{tool.label}</h2>
            <p className="muted">{DESCRIPTIONS[tool.to] ?? "Open tool"}</p>
          </Link>
        ))}
      </section>
    </div>
  );
}
