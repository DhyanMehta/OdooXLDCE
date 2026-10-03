import { useState } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";
import type { MemberPerson } from "../../types/api";

const PAGE_SIZE = 25;

export function AdminMembersPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<MemberPerson | null>(null);

  const membersRes = useAsyncResource(
    clubId && hasPermission("manage_members")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/members", {
            params: {
              path: { club_id: clubId },
              query: {
                limit: PAGE_SIZE,
                offset,
                ...(search.trim() ? { q: search.trim() } : {}),
              },
            },
          })
      : null,
    [clubId, hasPermission("manage_members"), offset, search],
    { cacheKeys: clubId ? [clubKey(clubId, "members")] : [] },
  );

  const historyRes = useAsyncResource(
    clubId && selected
      ? () =>
          api.get("/api/v1/clubs/{club_id}/members/{user_id}/memberships", {
            params: { path: { club_id: clubId, user_id: selected.user_id } },
          })
      : null,
    [clubId, selected?.user_id],
    {
      cacheKeys:
        clubId && selected
          ? [clubKey(clubId, `member-history:${selected.user_id}`)]
          : [],
    },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_members")) return <Feedback tone="danger">Forbidden</Feedback>;

  const page = membersRes.data;
  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const history = historyRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Members</h1>
        <p className="muted">Affiliation vs paid membership state for this club.</p>
      </div>

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setSearch(q);
        }}
      >
        <label style={{ flex: 1 }}>
          Search
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name or email"
          />
        </label>
        <button className="btn" type="submit" style={{ alignSelf: "end" }}>
          Search
        </button>
      </form>

      <PageState
        loading={membersRes.loading}
        error={membersRes.error}
        empty={items.length === 0}
        emptyMessage="No members found."
      >
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Affiliation</th>
                <th>Paid state</th>
                <th>Plan</th>
                <th>Pending dues</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr
                  key={r.user_id}
                  className={selected?.user_id === r.user_id ? "row-selected" : undefined}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelected(r)}
                >
                  <td>{r.full_name}</td>
                  <td>{r.email}</td>
                  <td>
                    {r.is_affiliated ? (
                      <span className="badge">Affiliated</span>
                    ) : (
                      <span className="badge badge--warn">No</span>
                    )}
                  </td>
                  <td>
                    <span className={statusBadgeClass(r.effective_state)}>{r.effective_state}</span>
                  </td>
                  <td>{r.current_plan_name ?? "—"}</td>
                  <td>{r.pending_dues_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <div className="pagination">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={offset === 0 || membersRes.loading}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            Previous
          </button>
          <span className="muted small">
            {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of {total}
          </span>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={offset + PAGE_SIZE >= total || membersRes.loading}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </PageState>

      {selected && (
        <section className="panel stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>
              History · {selected.full_name}
            </h2>
            <button className="btn btn--ghost" type="button" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
          <p className="muted small">
            Affiliation: {selected.is_affiliated ? "yes" : "no"} · Paid state:{" "}
            {selected.effective_state} · Pending dues: {selected.pending_dues_count}
          </p>
          <PageState
            loading={historyRes.loading}
            error={historyRes.error}
            empty={history.length === 0}
            emptyMessage="No paid membership history."
          >
            <table>
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>State</th>
                  <th>Starts</th>
                  <th>Ends</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map((m) => (
                  <tr key={m.id}>
                    <td>{m.plan_name ?? "—"}</td>
                    <td>
                      <span className={statusBadgeClass(m.effective_state ?? m.status)}>
                        {m.effective_state ?? m.status}
                      </span>
                    </td>
                    <td>{new Date(m.starts_at).toLocaleString()}</td>
                    <td>{new Date(m.ends_at).toLocaleString()}</td>
                    <td>{m.status}</td>
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
