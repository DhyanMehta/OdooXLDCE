import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";
const PAGE_SIZE = 20;

export function AnnouncementsPage() {
  const { activeClub, me } = useAuth();
  const [params] = useSearchParams();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const listRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/announcements", {
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
    [clubId, offset, search],
    { cacheKeys: clubId ? [clubKey(clubId, "announcements")] : [] },
  );

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club from the <Link to="/clubs">clubs directory</Link>, or select an active club in
        the sidebar.
      </Feedback>
    );
  }

  const page = listRes.data;
  const items = page?.items ?? [];
  const total = page?.total ?? 0;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Announcements</h1>
        <p className="muted">
          {clubName ?? "Club"} — members-only items appear only with an active membership.
        </p>
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
            placeholder="Search published history"
          />
        </label>
        <button className="btn" type="submit" style={{ alignSelf: "end" }}>
          Search
        </button>
      </form>
      <PageState
        loading={listRes.loading}
        error={listRes.error}
        empty={items.length === 0}
        emptyMessage="No announcements."
      >
        {items.map((item) => (
          <article key={item.id} className="panel stack">
            <div className="row">
              <h2>
                <Link to={`/announcements/${item.id}?club=${clubId}`}>{item.title}</Link>
              </h2>
              <span className="badge">{item.visibility}</span>
            </div>
            <p className="muted">{item.body.slice(0, 160)}{item.body.length > 160 ? "…" : ""}</p>
            <p className="muted small">
              {item.published_at ? new Date(item.published_at).toLocaleString() : item.status}
            </p>
          </article>
        ))}
        <div className="pagination">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={offset === 0 || listRes.loading}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            Newer
          </button>
          <span className="muted small">
            {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of {total}
          </span>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={offset + PAGE_SIZE >= total || listRes.loading}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Older
          </button>
        </div>
      </PageState>
    </div>
  );
}
