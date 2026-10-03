import { Link } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { api } from "../../services/api";

export function MyAssignmentsPage() {
  const { me, activeClub } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const assignmentsRes = useAsyncResource(
    me
      ? () =>
          api.get("/api/v1/me/assignments", {
            params: { query: clubId ? { club_id: clubId } : {} },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: ["my-assignments"] },
  );

  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/my-assignments">log in</Link>.
      </Feedback>
    );
  }

  const items = assignmentsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>My volunteering</h1>
        <p className="muted">
          {activeClub
            ? `Assignments for ${activeClub.club.name}.`
            : "All clubs — pick a club in the sidebar to filter."}
        </p>
      </div>

      <PageState
        loading={assignmentsRes.loading}
        error={assignmentsRes.error}
        empty={items.length === 0}
        emptyMessage="No task sign-ups yet."
      >
        <section className="panel stack">
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Task</th>
                <th>Status</th>
                <th>Signed up</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>{a.project_title ?? "—"}</td>
                  <td>{a.task_title ?? "—"}</td>
                  <td>
                    <span className={statusBadgeClass(a.status)}>{a.status}</span>
                  </td>
                  <td>{new Date(a.signed_up_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </PageState>

      {activeClub && (
        <Link className="btn btn--ghost" to={`/projects?club=${activeClub.club.id}`}>
          Browse projects
        </Link>
      )}
    </div>
  );
}
