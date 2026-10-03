import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, formatApiError } from "../../services/api";
import type { SubscriberPage } from "../../types/api";

const PAGE_SIZE = 25;

export function AdminMailingListPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const [page, setPage] = useState<SubscriberPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "pending" | "unsubscribed">("all");
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function reload(nextOffset = offset) {
    if (!clubId) return;
    setLoading(true);
    setError(null);
    try {
      setPage(
        await api.get("/api/v1/clubs/{club_id}/mailing-list", {
          params: {
            path: { club_id: clubId },
            query: {
              limit: PAGE_SIZE,
              offset: nextOffset,
              ...(filter !== "all" ? { status: filter } : {}),
              ...(search.trim() ? { q: search.trim() } : {}),
            },
          },
        }),
      );
    } catch (err) {
      setError(formatApiError(err));
      setPage(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId, filter, offset, search]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_mailing_list")) {
    return (
      <Feedback tone="danger">Forbidden — communications officers manage the mailing list.</Feedback>
    );
  }

  const rows = page?.items ?? [];
  const total = page?.total ?? 0;

  async function addSubscriber(e: FormEvent) {
    e.preventDefault();
    if (!clubId) return;
    if (!consent) {
      setError("Consent is required to subscribe.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const res = await api.post("/api/v1/clubs/{club_id}/mailing-list/subscribe", {
        params: { path: { club_id: clubId } },
        body: { email, consent: true },
      });
      setMessage(res.message);
      setEmail("");
      setConsent(false);
      setOffset(0);
      await reload(0);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeSubscriber(id: string) {
    if (!clubId) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/mailing-list/{subscription_id}/unsubscribe", {
        params: { path: { club_id: clubId, subscription_id: id } },
      });
      setMessage("Subscriber unsubscribed.");
      await reload(offset);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Mailing list</h1>
        <p className="muted">
          Subscribers receive published announcements. Public signup is on the{" "}
          <Link to="/clubs">club page</Link>.
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
        <label className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          <span>I confirm consent to email this address club announcements.</span>
        </label>
        <button className="btn" type="submit" disabled={busy || !consent}>
          Subscribe email
        </button>
      </form>

      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <h2>Subscribers</h2>
          <div className="row">
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                setOffset(0);
                setSearch(q);
              }}
            >
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search email"
                aria-label="Search email"
              />
              <button className="btn btn--ghost" type="submit">
                Search
              </button>
            </form>
            <select
              aria-label="Filter status"
              value={filter}
              onChange={(e) => {
                setOffset(0);
                setFilter(e.target.value as typeof filter);
              }}
              style={{ width: "auto" }}
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="unsubscribed">Unsubscribed</option>
            </select>
          </div>
        </div>
        {loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>No subscribers yet.</Empty>
        ) : (
          <>
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
                      <span
                        className={`badge ${row.status === "active" ? "" : "badge--warn"}`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="muted small">{new Date(row.consent_at).toLocaleString()}</td>
                    <td>
                      {(row.status === "active" || row.status === "pending") && (
                        <button
                          type="button"
                          className="btn btn--ghost"
                          disabled={busy}
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
    </div>
  );
}
