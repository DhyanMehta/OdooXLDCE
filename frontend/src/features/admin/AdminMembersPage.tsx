import { useEffect, useState } from "react";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";

type MemberRow = {
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  starts_at: string;
  ends_at: string;
  status: string;
};

export function AdminMembersPage() {
  const { activeClub, hasPermission } = useAuth();
  const [rows, setRows] = useState<MemberRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeClub || !hasPermission("manage_members")) return;
    api
      .get<MemberRow[]>(`/api/v1/clubs/${activeClub.club.id}/members`)
      .then(setRows)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed"));
  }, [activeClub, hasPermission]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_members")) return <Feedback tone="danger">Forbidden</Feedback>;
  if (error) return <Feedback tone="danger">{error}</Feedback>;
  if (!rows.length) return <Spinner />;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Members & dues</h1>
      </div>
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Status</th>
              <th>Ends</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.membership_id}>
                <td>{r.full_name}</td>
                <td>{r.email}</td>
                <td>{r.status}</td>
                <td>{new Date(r.ends_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
