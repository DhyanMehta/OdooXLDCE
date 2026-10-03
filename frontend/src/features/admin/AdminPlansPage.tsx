import { useEffect, useState, type FormEvent } from "react";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { Plan } from "../../types/api";

export function AdminPlansPage() {
  const { activeClub, hasPermission } = useAuth();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("Member ticket pricing benefit.");
  const [dues, setDues] = useState("300");
  const [days, setDays] = useState("180");
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    if (!activeClub) return;
    setPlans(await api.get<Plan[]>(`/api/v1/clubs/${activeClub.club.id}/plans`));
  }

  useEffect(() => {
    void reload();
  }, [activeClub]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_plans")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/plans`, {
        name,
        description,
        dues_amount: dues,
        duration_days: Number(days),
        fixed_expires_on: null,
        is_active: true,
      });
      setName("");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Membership plans</h1>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      <form className="panel form" onSubmit={onSubmit}>
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
          Duration days
          <input value={days} onChange={(e) => setDays(e.target.value)} required />
        </label>
        <button className="btn" type="submit">
          Create plan
        </button>
      </form>
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Dues</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>₹{p.dues_amount}</td>
                <td>{p.duration_days ?? p.fixed_expires_on}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
