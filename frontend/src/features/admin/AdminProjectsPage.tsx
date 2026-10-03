import { useState, type FormEvent } from "react";
import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { components } from "../../types/openapi";

type ProjectOut = components["schemas"]["ProjectOut"];

type TaskOut = components["schemas"]["TaskOut"];

export function AdminProjectsPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const [projectTitle, setProjectTitle] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [projectStatus, setProjectStatus] = useState("draft");
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const [taskProjectId, setTaskProjectId] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [taskCapacity, setTaskCapacity] = useState("");
  const [editTaskId, setEditTaskId] = useState<string | null>(null);
  const [rosterTaskId, setRosterTaskId] = useState<string | null>(null);
  const [assignUserId, setAssignUserId] = useState("");
  const [memberPick, setMemberPick] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const projectsRes = useAsyncResource(
    clubId && hasPermission("manage_projects")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/projects", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, hasPermission("manage_projects")],
    { cacheKeys: clubId ? [clubKey(clubId, "projects")] : [] },
  );
  const membersRes = useAsyncResource(
    clubId && hasPermission("manage_projects") && rosterTaskId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/members", {
            params: { path: { club_id: clubId }, query: { limit: 50, offset: 0 } },
          })
      : null,
    [clubId, rosterTaskId, hasPermission("manage_projects")],
    { cacheKeys: clubId ? [clubKey(clubId, "members")] : [] },
  );
  const rosterRes = useAsyncResource(
    clubId && rosterTaskId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/tasks/{task_id}/roster", {
            params: { path: { club_id: clubId, task_id: rosterTaskId } },
          })
      : null,
    [clubId, rosterTaskId],
    { cacheKeys: clubId && rosterTaskId ? [clubKey(clubId, `roster:${rosterTaskId}`)] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;

  if (!hasPermission("manage_projects")) return <Feedback tone="danger">Forbidden</Feedback>;
  function bump() {
    invalidate(clubKey(activeClub!.club.id, "projects"), "my-assignments");

  }
  function resetProjectForm() {
    setEditProjectId(null);
    setProjectTitle("");
    setProjectDescription("");
    setProjectStatus("draft");

  }
  function startEditProject(p: ProjectOut) {
    setEditProjectId(p.id);
    setProjectTitle(p.title);
    setProjectDescription(p.description);
    setProjectStatus(p.status);

  }
  function startEditTask(task: TaskOut, projectId: string) {
    setEditTaskId(task.id);
    setTaskProjectId(projectId);
    setTaskTitle(task.title);
    setTaskDescription(task.description);
    setTaskCapacity(task.capacity != null ? String(task.capacity) : "");

  }
  function resetTaskForm() {
    setEditTaskId(null);
    setTaskProjectId(null);
    setTaskTitle("");
    setTaskDescription("");
    setTaskCapacity("");

  }
  async function onProjectSubmit(e: FormEvent) {
    e.preventDefault();
    if (!clubId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (editProjectId) {
        await api.patch("/api/v1/clubs/{club_id}/projects/{project_id}", {
          params: { path: { club_id: clubId, project_id: editProjectId } },
          body: { title: projectTitle, description: projectDescription, status: projectStatus },
        });
        setMessage("Project updated.");
      } else {
        await api.post("/api/v1/clubs/{club_id}/projects", {
          params: { path: { club_id: clubId } },
          body: { title: projectTitle, description: projectDescription, status: projectStatus },
        });
        setMessage("Project created.");
      }
      resetProjectForm();
      bump();
      await projectsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }

  }
  async function onTaskSubmit(e: FormEvent) {
    e.preventDefault();
    if (!clubId || !taskProjectId) return;
    setBusy(true);
    setError(null);
    try {
      const capacity = taskCapacity.trim() ? Number(taskCapacity) : null;
      if (editTaskId) {
        await api.patch("/api/v1/clubs/{club_id}/tasks/{task_id}", {
          params: { path: { club_id: clubId, task_id: editTaskId } },
          body: {
            title: taskTitle,
            description: taskDescription,
            capacity,
            clear_capacity: false,
            clear_deadline: false,
          },
        });
        setMessage("Task updated.");
      } else {
        await api.post("/api/v1/clubs/{club_id}/projects/{project_id}/tasks", {
          params: { path: { club_id: clubId, project_id: taskProjectId } },
          body: {
            title: taskTitle,
            description: taskDescription,
            status: "open",
            capacity,
          },
        });
        setMessage("Task created.");
      }
      resetTaskForm();
      bump();
      await projectsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }

  }
  async function assignToTask(taskId: string) {
    if (!clubId) return;
    const userId = memberPick || assignUserId.trim();
    if (!userId) {
      setError("Pick a member or enter a user id.");
      return;
    }
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/tasks/{task_id}/assign", {
        params: { path: { club_id: clubId, task_id: taskId } },
        body: { user_id: userId },
      });
      setMessage("Member assigned.");
      bump();
      invalidate(clubKey(clubId, `roster:${taskId}`));
      await rosterRes.reload();
      await projectsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }

  }
  async function setAssignmentStatus(assignmentId: string, status: string) {
    if (!clubId) return;
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/assignments/{assignment_id}/status", {
        params: { path: { club_id: clubId, assignment_id: assignmentId } },
        body: { status },
      });
      bump();
      if (rosterTaskId) {
        invalidate(clubKey(clubId, `roster:${rosterTaskId}`));
        await rosterRes.reload();
      }
    } catch (err) {
      setError(formatApiError(err));
    }

  }
  const projects = projectsRes.data ?? [];
  const members = membersRes.data?.items ?? [];
  const roster = rosterRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Projects</h1>
        <p className="muted">Create projects, tasks, rosters, and assignment status.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}
      <form className="panel form" onSubmit={onProjectSubmit}>
        <h2>{editProjectId ? "Edit project" : "Create project"}</h2>
        <label>
          Title
          <input value={projectTitle} onChange={(e) => setProjectTitle(e.target.value)} required />
        </label>
        <label>
          Description
          <textarea value={projectDescription} onChange={(e) => setProjectDescription(e.target.value)} />
        </label>
        <label>
          Status
          <select value={projectStatus} onChange={(e) => setProjectStatus(e.target.value)}>
            <option value="draft">draft</option>
            <option value="open">open</option>
            <option value="closed">closed</option>
            <option value="archived">archived</option>
          </select>
        </label>
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            {editProjectId ? "Save project" : "Create project"}
          </button>
          {editProjectId && (
            <button className="btn btn--ghost" type="button" onClick={resetProjectForm}>
              Cancel
            </button>
          )}
        </div>
      </form>
      {(taskProjectId || editTaskId) && (
        <form className="panel form" onSubmit={onTaskSubmit}>
          <h2>{editTaskId ? "Edit task" : "Create task"}</h2>
          {!editTaskId && (
            <label>
              Project
              <select
                value={taskProjectId ?? ""}
                onChange={(e) => setTaskProjectId(e.target.value || null)}
                required
              >
                <option value="">Select project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Title
            <input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} required />
          </label>
          <label>
            Description
            <textarea value={taskDescription} onChange={(e) => setTaskDescription(e.target.value)} />
          </label>
          <label>
            Capacity (optional)
            <input
              type="number"
              min={1}
              value={taskCapacity}
              onChange={(e) => setTaskCapacity(e.target.value)}
            />
          </label>
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>
              {editTaskId ? "Save task" : "Create task"}
            </button>
            <button className="btn btn--ghost" type="button" onClick={resetTaskForm}>
              Cancel
            </button>
          </div>
        </form>
      )}
      <PageState
        loading={projectsRes.loading}
        error={projectsRes.error}
        empty={projects.length === 0}
        emptyMessage="No projects yet."
      >
        <section className="panel stack">
          {projects.map((p) => (
            <div key={p.id} className="stack">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>{p.title}</strong>{" "}
                  <span className={statusBadgeClass(p.status)}>{p.status}</span>
                  <div className="muted small">{p.description}</div>
                </div>
                <div className="row">
                  <button className="btn btn--ghost" type="button" onClick={() => startEditProject(p)}>
                    Edit
                  </button>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => {
                      setTaskProjectId(p.id);
                      setEditTaskId(null);
                      setTaskTitle("");
                      setTaskDescription("");
                      setTaskCapacity("");
                    }}
                  >
                    Add task
                  </button>
                </div>
              </div>
              {p.tasks.map((t) => (
                <div key={t.id} className="row muted small" style={{ justifyContent: "space-between" }}>
                  <span>
                    {t.title} · <span className={statusBadgeClass(t.status)}>{t.status}</span> ·{" "}
                    {t.active_count ?? 0}/{t.capacity ?? "∞"}
                  </span>
                  <div className="row">
                    <button className="btn btn--ghost" type="button" onClick={() => startEditTask(t, p.id)}>
                      Edit
                    </button>
                    <button
                      className="btn btn--ghost"
                      type="button"
                      onClick={() => setRosterTaskId(t.id)}
                    >
                      Roster
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </section>
      </PageState>
      {rosterTaskId && (
        <section className="panel stack">
          <h2>Task roster</h2>
          <div className="form row">
            {members.length > 0 ? (
              <label style={{ flex: 1 }}>
                Member
                <select value={memberPick} onChange={(e) => setMemberPick(e.target.value)}>
                  <option value="">Select member</option>
                  {members.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name} ({m.user_id.slice(0, 8)}…)
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label style={{ flex: 1 }}>
                User id
                <input value={assignUserId} onChange={(e) => setAssignUserId(e.target.value)} />
              </label>
            )}
            <button className="btn" type="button" onClick={() => void assignToTask(rosterTaskId)}>
              Assign
            </button>
            <button className="btn btn--ghost" type="button" onClick={() => setRosterTaskId(null)}>
              Close
            </button>
          </div>
          <PageState
            loading={rosterRes.loading}
            error={rosterRes.error}
            empty={roster.length === 0}
            emptyMessage="No assignments yet."
          >
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {roster.map((a) => (
                  <tr key={a.id}>
                    <td>{a.user_name ?? a.user_email ?? a.user_id}</td>
                    <td>
                      <span className={statusBadgeClass(a.status)}>{a.status}</span>
                    </td>
                    <td className="row">
                      {["active", "completed", "cancelled"].map((st) => (
                        <button
                          key={st}
                          className="btn btn--ghost"
                          type="button"
                          onClick={() => void setAssignmentStatus(a.id, st)}
                        >
                          {st}
                        </button>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </PageState>
        </section>
      )}
    </div>
  );
}
