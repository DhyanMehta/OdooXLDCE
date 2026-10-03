import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";

type Subscriber = {
  id: string;
  email: string;
  status: string;
  consent_at: string;
  created_at: string;
  unsubscribed_at: string | null;
};

export function AdminMailingListPage() {
  const { activeClub, hasPermission } = useAuth();
  const [rows, setRows] = useState<Subscriber[]>([]);
  const [email, setEmail] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "unsubscribed">("all");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function reload() {
    if (!activeClub) return;
    setLoading(true);
    setError(null);
    try {
      const q = filter === "all" ? "" : `?status=${filter}`;
      setRows(await api.get<Subscriber[]>(`/api/v1/clubs/${activeClub.club.id}/mailing-list${q}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load mailing list");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [activeClub, filter]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_mailing_list")) {
    return <Feedback tone="danger">Forbidden — communications officers manage the mailing list.</Feedback>;
  }

  async function addSubscriber(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    setError(null);
    try {
      const res = await api.post<{ message: string }>(
        `/api/v1/clubs/${activeClub!.club.id}/mailing-list/subscribe`,
        { email },
      );
      setMessage(res.message);
      setEmail("");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Subscribe failed");
    }
  }

  async function removeSubscriber(id: string) {
    setMessage(null);
    setError(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/mailing-list/${id}/unsubscribe`);
      setMessage("Subscriber unsubscribed.");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unsubscribe failed");
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Mailing list</h1>
        <p className="muted">
          Subscribers receive published announcements. Public signup is on the{" "}
          <Link to="/clubs/tech-club">club page</Link>.
        </p>
      </div>

      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <form className="panel form" onSubmit={addSubscriber}>
        <h2>Add subscriber</h2>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="name@example.com"
          />
        </label>
        <button className="btn" type="submit">
          Subscribe email
        </button>
      </form>

      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Subscribers</h2>
          <select
            aria-label="Filter status"
            value={filter}
            onChange={(e) => setFilter(e.target.value as typeof filter)}
            style={{ width: "auto" }}
          >
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="unsubscribed">Unsubscribed</option>
          </select>
        </div>
        {loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>No subscribers yet.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Status</th>
                <th>Consent</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.email}</td>
                  <td>
                    <span className={`badge ${row.status === "active" ? "" : "badge--warn"}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="muted small">{new Date(row.consent_at).toLocaleString()}</td>
                  <td>
                    {row.status === "active" && (
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => void removeSubscriber(row.id)}
                      >
                        Unsubscribe
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
