import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { prettyRoleCode } from "../../lib/roles";
import { api, ApiError } from "../../services/api";

type Assignment = {
  id: string;
  user_id: string;
  user_email: string | null;
  user_name: string | null;
  role_code: string | null;
  starts_at: string;
  ends_at: string | null;
};

type DirectoryPerson = {
  user_id: string;
  full_name: string;
  email: string;
};

export function RolesPage() {
  const { activeClub, hasPermission } = useAuth();
  const [rows, setRows] = useState<Assignment[]>([]);
  const [people, setPeople] = useState<DirectoryPerson[]>([]);
  const [outgoingId, setOutgoingId] = useState("");
  const [incomingUserId, setIncomingUserId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function reload() {
    if (!activeClub) return;
    const [assignments, directory] = await Promise.all([
      api.get<Assignment[]>(
        `/api/v1/clubs/${activeClub.club.id}/role-assignments?include_history=true`,
      ),
      api.get<DirectoryPerson[]>(`/api/v1/clubs/${activeClub.club.id}/directory`),
    ]);
    setRows(assignments);
    setPeople(directory);
    const active = assignments.filter((a) => !a.ends_at);
    if (!outgoingId && active[0]) setOutgoingId(active[0].id);
    if (!incomingUserId && directory[0]) setIncomingUserId(directory[0].user_id);
  }

  useEffect(() => {
    void reload().catch((err: unknown) =>
      setError(err instanceof ApiError ? err.message : "Failed to load roles"),
    );
  }, [activeClub]);

  const activeAssignments = useMemo(() => rows.filter((r) => !r.ends_at), [rows]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_roles")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function handover(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/role-assignments/handover`, {
        outgoing_assignment_id: outgoingId,
        incoming_user_id: incomingUserId,
      });
      setMessage("Role transferred.");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Handover failed");
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Roles</h1>
        <p className="muted">Assign and transfer club leadership. History is kept.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>Person</th>
              <th>Role</th>
              <th>Starts</th>
              <th>Ends</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <strong>{r.user_name ?? "Unknown"}</strong>
                  <div className="muted small">{r.user_email}</div>
                </td>
                <td>{prettyRoleCode(r.role_code)}</td>
                <td>{new Date(r.starts_at).toLocaleString()}</td>
                <td>{r.ends_at ? new Date(r.ends_at).toLocaleString() : "Active"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <form className="panel form" onSubmit={handover}>
        <h2>Transfer role</h2>
        <label>
          Current assignment
          <select value={outgoingId} onChange={(e) => setOutgoingId(e.target.value)} required>
            {activeAssignments.map((a) => (
              <option key={a.id} value={a.id}>
                {a.user_name} — {prettyRoleCode(a.role_code)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Transfer to
          <select
            value={incomingUserId}
            onChange={(e) => setIncomingUserId(e.target.value)}
            required
          >
            {people.map((p) => (
              <option key={p.user_id} value={p.user_id}>
                {p.full_name} ({p.email})
              </option>
            ))}
          </select>
        </label>
        <button className="btn" type="submit">
          Transfer
        </button>
      </form>
    </div>
  );
}
