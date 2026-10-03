import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";

export function ProjectsPage() {
  const { me, activeClub } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const projectsRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/projects", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "projects")] : [] },
  );
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

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club first from the <Link to="/clubs">clubs directory</Link>.
      </Feedback>
    );

  }
  const assignmentsByTask = new Map(
    (assignmentsRes.data ?? []).map((a) => [a.task_id, a]),
  );
  const projects = (projectsRes.data ?? []).filter((p) => p.status === "open");
  const openTaskCount = projects.reduce(
    (n, p) => n + p.tasks.filter((t) => t.status === "open").length,
    0,
  );
  async function signup(taskId: string) {
    if (!clubId) return;
    if (!me) {
      navigate(`/login?next=${encodeURIComponent(`/projects?club=${clubId}`)}`);
      return;
    }
    setBusyTaskId(taskId);
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/tasks/{task_id}/signup", {
        params: { path: { club_id: clubId, task_id: taskId } },
      });
      invalidate(clubKey(clubId, "projects"), "my-assignments");
      await projectsRes.reload();
      await assignmentsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyTaskId(null);
    }

  }
  async function withdraw(assignmentId: string, taskId: string) {
    if (!clubId) return;
    setBusyTaskId(taskId);
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/assignments/{assignment_id}/withdraw", {
        params: { path: { club_id: clubId, assignment_id: assignmentId } },
      });
      invalidate(clubKey(clubId, "projects"), "my-assignments");
      await projectsRes.reload();
      await assignmentsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyTaskId(null);
    }

  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Projects & volunteering</h1>
        <p className="muted">{clubName ?? "Club"} — sign up for open tasks.</p>
      </div>
      {(error || projectsRes.error) && (
        <Feedback tone="danger">{error ?? projectsRes.error}</Feedback>
      )}
      <PageState
        loading={projectsRes.loading}
        error={null}
        empty={openTaskCount === 0}
        emptyMessage="No open tasks right now."
      >
        {projects.map((project) => {
          const openTasks = project.tasks.filter((t) => t.status === "open");
          if (openTasks.length === 0) return null;
          return (
            <section key={project.id} className="panel stack">
              <h2>{project.title}</h2>
              {project.description && <p className="muted">{project.description}</p>}
              {openTasks.map((task) => {
                const assignment = assignmentsByTask.get(task.id);
                const active = task.active_count ?? 0;
                const cap = task.capacity;
                const full = cap != null && active >= cap;
                return (
                  <div key={task.id} className="row" style={{ justifyContent: "space-between" }}>
                    <div>
                      <strong>{task.title}</strong>
                      <div className="muted small">
                        {task.description}
                        {task.deadline && (
                          <> · deadline {new Date(task.deadline).toLocaleString()}</>
                        )}
                      </div>
                      <span className={statusBadgeClass(task.status)}>{task.status}</span>{" "}
                      <span className="badge">
                        {active}/{cap ?? "∞"} signed up
                      </span>
                    </div>
                    <div className="row">
                      {assignment ? (
                        <>
                          <span className="muted small">You: {assignment.status}</span>
                          <button
                            className="btn btn--ghost"
                            type="button"
                            disabled={busyTaskId === task.id}
                            onClick={() => void withdraw(assignment.id, task.id)}
                          >
                            Withdraw
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn"
                          type="button"
                          disabled={full || busyTaskId === task.id || !me}
                          onClick={() => void signup(task.id)}
                        >
                          {!me ? "Log in to sign up" : full ? "Full" : busyTaskId === task.id ? "…" : "Sign up"}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </section>
          );
        })}
      </PageState>
      <section className="panel row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2>My volunteering</h2>
          <p className="muted">Tasks you signed up for across this club.</p>
        </div>
        {me ? (
          <Link className="btn btn--ghost" to="/my-assignments">
            View assignments
          </Link>
        ) : (
          <Link className="btn btn--ghost" to={`/login?next=${encodeURIComponent("/my-assignments")}`}>
            Log in
          </Link>
        )}
      </section>
    </div>
  );
}
