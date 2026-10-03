import { useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { Plan } from "../../types/api";

type DurationMode = "duration" | "fixed";

export function AdminPlansPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("Member ticket pricing benefit.");
  const [dues, setDues] = useState("300");
  const [mode, setMode] = useState<DurationMode>("duration");
  const [days, setDays] = useState("180");
  const [fixedOn, setFixedOn] = useState("");
  const [editId, setEditId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const plansRes = useAsyncResource(
    clubId && hasPermission("manage_plans")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/plans", {
            params: { path: { club_id: clubId }, query: { include_inactive: true } },
          })
      : null,
    [clubId, hasPermission("manage_plans")],
    { cacheKeys: clubId ? [clubKey(clubId, "plans")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_plans")) return <Feedback tone="danger">Forbidden</Feedback>;

  function resetForm() {
    setEditId(null);
    setName("");
    setDescription("Member ticket pricing benefit.");
    setDues("300");
    setMode("duration");
    setDays("180");
    setFixedOn("");
  }

  function startEdit(plan: Plan) {
    setEditId(plan.id);
    setName(plan.name);
    setDescription(plan.description);
    setDues(String(plan.dues_amount));
    if (plan.duration_days != null) {
      setMode("duration");
      setDays(String(plan.duration_days));
      setFixedOn("");
    } else {
      setMode("fixed");
      setFixedOn(plan.fixed_expires_on ?? "");
      setDays("");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setBusy(true);
    const body = {
      name,
      description,
      dues_amount: dues,
      duration_days: mode === "duration" ? Number(days) : null,
      fixed_expires_on: mode === "fixed" ? fixedOn : null,
      is_active: true,
    };
    try {
      if (editId) {
        await api.patch("/api/v1/clubs/{club_id}/plans/{plan_id}", {
          params: { path: { club_id: activeClub!.club.id, plan_id: editId } },
          body: {
            name: body.name,
            description: body.description,
            dues_amount: body.dues_amount,
            duration_days: body.duration_days,
            fixed_expires_on: body.fixed_expires_on,
          },
        });
        setMessage("Plan updated.");
      } else {
        await api.post("/api/v1/clubs/{club_id}/plans", {
          params: { path: { club_id: activeClub!.club.id } },
          body,
        });
        setMessage("Plan created.");
      }
      resetForm();
      invalidate(clubKey(activeClub!.club.id, "plans"));
      await plansRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function patchPlan(
    planId: string,
    fields: {
      archived?: boolean | null;
      is_active?: boolean | null;
      name?: string | null;
      description?: string | null;
      dues_amount?: number | string | null;
      duration_days?: number | null;
      fixed_expires_on?: string | null;
    },
  ) {
    setError(null);
    setMessage(null);
    try {
      await api.patch("/api/v1/clubs/{club_id}/plans/{plan_id}", {
        params: { path: { club_id: activeClub!.club.id, plan_id: planId } },
        body: fields,
      });
      invalidate(clubKey(activeClub!.club.id, "plans"));
      await plansRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  const plans = plansRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Membership plans</h1>
        <p className="muted">Duration days and fixed end date are mutually exclusive.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <form className="panel form" onSubmit={onSubmit}>
        <h2>{editId ? "Edit plan" : "Create plan"}</h2>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Description
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          Dues amount
          <input value={dues} onChange={(e) => setDues(e.target.value)} required />
        </label>
        <label>
          Term type
          <select value={mode} onChange={(e) => setMode(e.target.value as DurationMode)}>
            <option value="duration">Duration (days)</option>
            <option value="fixed">Fixed end date</option>
          </select>
        </label>
        {mode === "duration" ? (
          <label>
            Duration days
            <input
              type="number"
              min={1}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              required
            />
          </label>
        ) : (
          <label>
            Fixed expires on
            <input
              type="date"
              value={fixedOn}
              onChange={(e) => setFixedOn(e.target.value)}
              required
            />
          </label>
        )}
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving…" : editId ? "Save changes" : "Create plan"}
          </button>
          {editId && (
            <button className="btn btn--ghost" type="button" onClick={resetForm}>
              Cancel edit
            </button>
          )}
        </div>
      </form>

      <PageState
        loading={plansRes.loading}
        error={plansRes.error}
        empty={plans.length === 0}
        emptyMessage="No plans yet. Create one above."
      >
        <section className="panel stack">
          {plans.map((p) => (
            <div key={p.id} className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong>{p.name}</strong>{" "}
                {!p.is_active && <span className="badge badge--warn">inactive</span>}
                {p.archived_at && <span className="badge badge--danger">archived</span>}
                <div className="muted small">
                  ₹{p.dues_amount} ·{" "}
                  {p.duration_days != null
                    ? `${p.duration_days} days`
                    : p.fixed_expires_on
                      ? `until ${p.fixed_expires_on}`
                      : "—"}
                </div>
              </div>
              <div className="row">
                <button className="btn btn--ghost" type="button" onClick={() => startEdit(p)}>
                  Edit
                </button>
                {p.is_active ? (
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => void patchPlan(p.id, { is_active: false })}
                  >
                    Deactivate
                  </button>
                ) : (
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => void patchPlan(p.id, { is_active: true })}
                  >
                    Activate
                  </button>
                )}
                {!p.archived_at && (
                  <button
                    className="btn btn--danger"
                    type="button"
                    onClick={() => {
                      if (window.confirm("Archive this plan?")) {
                        void patchPlan(p.id, { archived: true, is_active: false });
                      }
                    }}
                  >
                    Archive
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>
      </PageState>
    </div>
  );
}
