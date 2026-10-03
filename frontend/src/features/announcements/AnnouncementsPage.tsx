import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { Announcement } from "../../types/api";

export function AnnouncementsPage() {
  const { activeClub } = useAuth();
  const [items, setItems] = useState<Announcement[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeClub) {
      setLoading(false);
      return;
    }
    const params = q ? `?q=${encodeURIComponent(q)}` : "";
    api
      .get<Announcement[]>(`/api/v1/clubs/${activeClub.club.id}/announcements${params}`)
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed"))
      .finally(() => setLoading(false));
  }, [activeClub, q]);

  if (!activeClub) {
    return (
      <Feedback tone="warn">
        Open the <Link to="/clubs/tech-club">public club page</Link> or log in first.
      </Feedback>
    );
  }
  if (loading) return <Spinner />;
  if (error) return <Feedback tone="danger">{error}</Feedback>;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Announcements</h1>
        <p className="muted">Members-only items appear only with an active membership.</p>
      </div>
      <label>
        Search
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search published history" />
      </label>
      {items.length === 0 ? (
        <Empty>No announcements.</Empty>
      ) : (
        items.map((item) => (
          <article key={item.id} className="panel stack">
            <div className="row">
              <h2>{item.title}</h2>
              <span className="badge">{item.visibility}</span>
            </div>
            <p>{item.body}</p>
            <p className="muted small">
              {item.published_at ? new Date(item.published_at).toLocaleString() : item.status}
            </p>
          </article>
        ))
      )}
    </div>
  );
}
