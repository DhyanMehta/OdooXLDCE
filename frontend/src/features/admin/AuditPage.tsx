import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";
export function AuditPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const auditRes = useAsyncResource(
    clubId && hasPermission("view_audit")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/audit-logs", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, hasPermission("view_audit")],
    { cacheKeys: clubId ? [clubKey(clubId, "audit")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("view_audit")) return <Feedback tone="danger">Forbidden</Feedback>;

  const rows = auditRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Audit history</h1>
        <p className="muted">Important club changes with actor and entity context.</p>
      </div>
      <PageState
        loading={auditRes.loading}
        error={auditRes.error}
        empty={rows.length === 0}
        emptyMessage="No audit entries yet."
      >
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    {r.actor_name ?? "—"}
                    {r.actor_email && <div className="muted small">{r.actor_email}</div>}
                  </td>
                  <td>{r.action}</td>
                  <td>{r.entity_label ?? r.entity_type.replaceAll("_", " ")}</td>
                  <td className="muted small mono">
                    {Object.keys(r.details ?? {}).length
                      ? JSON.stringify(r.details)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </PageState>
    </div>
  );
}
