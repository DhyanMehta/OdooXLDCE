import { useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { fromLocalInput, statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { prettyRoleCode } from "../../lib/roles";
import { api, formatApiError } from "../../services/api";
export function RolesPage() {
  const { activeClub, hasPermission, refresh } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const [assignUserId, setAssignUserId] = useState("");
  const [assignRole, setAssignRole] = useState("");
  const [assignStarts, setAssignStarts] = useState("");
  const [assignEnds, setAssignEnds] = useState("");
  const [outgoingId, setOutgoingId] = useState("");
  const [incomingUserId, setIncomingUserId] = useState("");
  const [endId, setEndId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const canManage = Boolean(clubId && hasPermission("manage_roles"));

  const assignmentsRes = useAsyncResource(
    canManage
      ? () =>
          api.get("/api/v1/clubs/{club_id}/role-assignments", {
            params: { path: { club_id: clubId! }, query: { include_history: true } },
          })
      : null,
    [clubId, canManage],
    { cacheKeys: clubId ? [clubKey(clubId, "roles")] : [] },
  );
  const peopleRes = useAsyncResource(
    canManage
      ? () =>
          api.get("/api/v1/clubs/{club_id}/directory", {
            params: { path: { club_id: clubId! } },
          })
      : null,
    [clubId, canManage],
    { cacheKeys: clubId ? [clubKey(clubId, "directory")] : [] },
  );
  const rolesRes = useAsyncResource(
    canManage
      ? () =>
          api.get("/api/v1/clubs/{club_id}/roles", {
            params: { path: { club_id: clubId! } },
          })
      : null,
    [clubId, canManage],
    { cacheKeys: ["roles-catalog"] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_roles")) return <Feedback tone="danger">Forbidden</Feedback>;

  const rows = assignmentsRes.data ?? [];
  const people = peopleRes.data ?? [];
  const roles = rolesRes.data ?? [];
  const activeAssignments = rows.filter((r) => r.state === "active" || (!r.state && !r.ends_at));

  async function afterChange(msg: string) {
    setMessage(msg);
    invalidate(clubKey(activeClub!.club.id, "roles"), clubKey(activeClub!.club.id, "directory"), "me");
    await refresh();
    await assignmentsRes.reload();
    await peopleRes.reload();
  }

  async function onAssign(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/role-assignments", {
        params: { path: { club_id: activeClub!.club.id } },
        body: {
          user_id: assignUserId,
          role_code: assignRole,
          starts_at: assignStarts ? fromLocalInput(assignStarts) : null,
          ends_at: assignEnds ? fromLocalInput(assignEnds) : null,
        },
      });
      setAssignStarts("");
      setAssignEnds("");
      await afterChange("Role assigned.");
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function onEnd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/role-assignments/{assignment_id}/end", {
        params: { path: { club_id: activeClub!.club.id, assignment_id: endId } },
      });
      await afterChange("Assignment ended.");
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function onHandover(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/role-assignments/handover", {
        params: { path: { club_id: activeClub!.club.id } },
        body: {
          outgoing_assignment_id: outgoingId,
          incoming_user_id: incomingUserId,
        },
      });
      await afterChange("Role transferred.");
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Roles</h1>
        <p className="muted">Assign, end, and handover club leadership. History is kept.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <PageState
        loading={assignmentsRes.loading}
        error={assignmentsRes.error}
        empty={rows.length === 0}
        emptyMessage="No role assignments yet."
      >
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Person</th>
                <th>Role</th>
                <th>State</th>
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
                  <td>
                    <span className={statusBadgeClass(r.state ?? (r.ends_at ? "ended" : "active"))}>
                      {r.state ?? (r.ends_at ? "ended" : "active")}
                    </span>
                  </td>
                  <td>{new Date(r.starts_at).toLocaleString()}</td>
                  <td>{r.ends_at ? new Date(r.ends_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </PageState>

      <form className="panel form" onSubmit={onAssign}>
        <h2>Assign role</h2>
        <label>
          Person
          <select
            value={assignUserId}
            onChange={(e) => setAssignUserId(e.target.value)}
            required
          >
            <option value="">Select…</option>
            {people.map((p) => (
              <option key={p.user_id} value={p.user_id}>
                {p.full_name} ({p.email})
              </option>
            ))}
          </select>
        </label>
        <label>
          Role
          <select value={assignRole} onChange={(e) => setAssignRole(e.target.value)} required>
            <option value="">Select…</option>
            {roles.map((r) => (
              <option key={r.id} value={r.code}>
                {r.name} ({r.code})
              </option>
            ))}
          </select>
        </label>
        <label>
          Starts (optional)
          <input
            type="datetime-local"
            value={assignStarts}
            onChange={(e) => setAssignStarts(e.target.value)}
          />
        </label>
        <label>
          Ends (optional)
          <input
            type="datetime-local"
            value={assignEnds}
            onChange={(e) => setAssignEnds(e.target.value)}
          />
        </label>
        <button className="btn" type="submit">
          Assign
        </button>
      </form>

      <form className="panel form" onSubmit={onEnd}>
        <h2>End assignment</h2>
        <label>
          Active / scheduled assignment
          <select value={endId} onChange={(e) => setEndId(e.target.value)} required>
            <option value="">Select…</option>
            {rows
              .filter((r) => r.state !== "ended")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.user_name} — {prettyRoleCode(a.role_code)} ({a.state ?? "active"})
                </option>
              ))}
          </select>
        </label>
        <button className="btn btn--danger" type="submit">
          End now
        </button>
      </form>

      <form className="panel form" onSubmit={onHandover}>
        <h2>Transfer role</h2>
        <label>
          Current assignment
          <select
            value={outgoingId || activeAssignments[0]?.id || ""}
            onChange={(e) => setOutgoingId(e.target.value)}
            required
          >
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
            value={incomingUserId || people[0]?.user_id || ""}
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
