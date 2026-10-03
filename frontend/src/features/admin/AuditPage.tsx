import { useEffect, useState } from "react";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";

type AuditRow = {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  actor_user_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export function AuditPage() {
  const { activeClub, hasPermission } = useAuth();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeClub || !hasPermission("view_audit")) return;
    api
      .get<AuditRow[]>(`/api/v1/clubs/${activeClub.club.id}/audit-logs`)
      .then(setRows)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed"));
  }, [activeClub, hasPermission]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("view_audit")) return <Feedback tone="danger">Forbidden</Feedback>;
  if (error) return <Feedback tone="danger">{error}</Feedback>;
  if (!rows.length) return <Spinner label="Loading audit history…" />;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Audit history</h1>
      </div>
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Action</th>
              <th>Entity</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.action}</td>
                <td>{r.entity_type.replaceAll("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
