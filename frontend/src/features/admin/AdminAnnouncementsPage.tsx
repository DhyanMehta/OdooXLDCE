import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, PageState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, formatApiError } from "../../services/api";
import type { Announcement, AnnouncementPage, Delivery } from "../../types/api";

const PAGE_SIZE = 20;

export function AdminAnnouncementsPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const [page, setPage] = useState<AnnouncementPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("public");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editBody, setEditBody] = useState("");
  const [editVisibility, setEditVisibility] = useState("public");
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  async function reload(nextOffset = offset) {
    if (!clubId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/v1/clubs/{club_id}/announcements", {
        params: {
          path: { club_id: clubId },
          query: { limit: PAGE_SIZE, offset: nextOffset },
        },
      });
      setPage(data);
    } catch (err) {
      setError(formatApiError(err));
      setPage(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadDeliveries(announcementId: string) {
    if (!clubId) return;
    setDeliveriesLoading(true);
    try {
      const rows = await api.get("/api/v1/clubs/{club_id}/announcements/{announcement_id}/deliveries", {
        params: { path: { club_id: clubId, announcement_id: announcementId } },
      });
      setDeliveries(rows);
    } catch (err) {
      setError(formatApiError(err));
      setDeliveries([]);
    } finally {
      setDeliveriesLoading(false);
    }
  }

  useEffect(() => {
    void reload(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId, offset]);

  useEffect(() => {
    if (!selectedId || !page) return;
    const item = page.items.find((a) => a.id === selectedId);
    if (!item) return;
    setEditTitle(item.title);
    setEditBody(item.body);
    setEditVisibility(item.visibility);
    void loadDeliveries(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_announcements")) {
    return <Feedback tone="danger">Forbidden</Feedback>;
  }

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const selected = items.find((a) => a.id === selectedId) ?? null;

  function selectAnnouncement(item: Announcement) {
    setSelectedId(item.id);
    setEditTitle(item.title);
    setEditBody(item.body);
    setEditVisibility(item.visibility);
    setMessage(null);
    setError(null);
  }

  async function createDraft(e: FormEvent) {
    e.preventDefault();
    if (!clubId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await api.post("/api/v1/clubs/{club_id}/announcements", {
        params: { path: { club_id: clubId } },
        body: { title, body, visibility },
      });
      setTitle("");
      setBody("");
      setVisibility("public");
      setMessage("Draft saved.");
      setOffset(0);
      await reload(0);
      setSelectedId(created.id);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveContent(e: FormEvent) {
    e.preventDefault();
    if (!clubId || !selectedId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.patch("/api/v1/clubs/{club_id}/announcements/{announcement_id}", {
        params: { path: { club_id: clubId, announcement_id: selectedId } },
        body: {
          title: editTitle,
          body: editBody,
          visibility: editVisibility,
        },
      });
      setMessage("Content updated (no email resent).");
      await reload(offset);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!clubId || !selectedId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/announcements/{announcement_id}/publish", {
        params: { path: { club_id: clubId, announcement_id: selectedId } },
      });
      setMessage("Published — deliveries queued.");
      await reload(offset);
      await loadDeliveries(selectedId);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function sendCorrection() {
    if (!clubId || !selectedId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/announcements/{announcement_id}/send-correction", {
        params: { path: { club_id: clubId, announcement_id: selectedId } },
      });
      setMessage("Correction notification queued.");
      await reload(offset);
      await loadDeliveries(selectedId);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Announcements</h1>
        <p className="muted">
          Edit content with PATCH (does not resend). Publish and send correction are explicit.
        </p>
      </div>

      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <form className="panel form" onSubmit={createDraft}>
        <h2>New draft</h2>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Body
          <textarea value={body} onChange={(e) => setBody(e.target.value)} required />
        </label>
        <label>
          Visibility
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="public">Public</option>
            <option value="members">Members only</option>
          </select>
        </label>
        <button className="btn" type="submit" disabled={busy}>
          Save draft
        </button>
      </form>

      <section className="panel stack">
        <h2>All announcements</h2>
        {loading ? (
          <Spinner />
        ) : items.length === 0 ? (
          <Empty>No announcements yet.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Visibility</th>
                  <th>Corrections</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={selectedId === item.id ? "row-selected" : undefined}
                    style={{ cursor: "pointer" }}
                    onClick={() => selectAnnouncement(item)}
                  >
                    <td>{item.title}</td>
                    <td>
                      <span className={`badge ${item.status === "draft" ? "badge--warn" : ""}`}>
                        {item.status}
                      </span>
                    </td>
                    <td>{item.visibility}</td>
                    <td>{item.correction_seq}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pagination">
              <button
                type="button"
                className="btn btn--ghost"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                Previous
              </button>
              <span className="muted small">
                {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of{" "}
                {total}
              </span>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={offset + PAGE_SIZE >= total || loading}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </section>

      {selected && (
        <section className="panel stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>Edit · {selected.title}</h2>
            <div className="row">
              <Link
                className="btn btn--ghost"
                to={`/announcements/${selected.id}?club=${clubId}&preview=1`}
              >
                Preview
              </Link>
              <button className="btn btn--ghost" type="button" onClick={() => setSelectedId(null)}>
                Close
              </button>
            </div>
          </div>

          <form className="form" onSubmit={saveContent}>
            <label>
              Title
              <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} required />
            </label>
            <label>
              Body
              <textarea value={editBody} onChange={(e) => setEditBody(e.target.value)} required />
            </label>
            <label>
              Visibility
              <select
                value={editVisibility}
                onChange={(e) => setEditVisibility(e.target.value)}
              >
                <option value="public">Public</option>
                <option value="members">Members only</option>
              </select>
            </label>
            <div className="row">
              <button className="btn" type="submit" disabled={busy}>
                Save content
              </button>
              {selected.status !== "published" && (
                <button className="btn" type="button" disabled={busy} onClick={() => void publish()}>
                  Publish
                </button>
              )}
              {selected.status === "published" && (
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={busy}
                  onClick={() => void sendCorrection()}
                >
                  Send correction
                </button>
              )}
            </div>
            <p className="muted small">
              Saving content does not email subscribers. Use Publish or Send correction explicitly.
            </p>
          </form>

          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>Deliveries</h3>
            <button
              className="btn btn--ghost"
              type="button"
              disabled={deliveriesLoading}
              onClick={() => void loadDeliveries(selected.id)}
            >
              Refresh deliveries
            </button>
          </div>
          <PageState
            loading={deliveriesLoading}
            error={null}
            empty={deliveries.length === 0}
            emptyMessage="No delivery rows yet."
          >
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Processed</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.recipient_email}</td>
                    <td>{d.kind}</td>
                    <td>
                      <span className="badge">{d.status.replaceAll("_", " ")}</span>
                    </td>
                    <td>{d.attempts}</td>
                    <td className="muted small">
                      {d.processed_at ? new Date(d.processed_at).toLocaleString() : "—"}
                    </td>
                    <td className="muted small">{d.last_error ?? "—"}</td>
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
