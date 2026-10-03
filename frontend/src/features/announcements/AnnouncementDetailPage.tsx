import { Link, useParams, useSearchParams } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";
export function AnnouncementDetailPage() {
  const { announcementId = "" } = useParams();
  const [params] = useSearchParams();
  const { activeClub, me } = useAuth();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const preview = params.get("preview") === "1" || params.get("preview") === "true";

  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;

  const detailRes = useAsyncResource(
    clubId && announcementId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/announcements/{announcement_id}", {
            params: {
              path: { club_id: clubId, announcement_id: announcementId },
              query: preview ? { preview: true } : {},
            },
          })
      : null,
    [clubId, announcementId, preview],
    {
      cacheKeys:
        clubId && announcementId
          ? [clubKey(clubId, "announcements"), `announcement:${announcementId}`]
          : [],
    },
  );

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Missing club context. Open from the{" "}
        <Link to="/announcements">announcements list</Link> (include <code>?club=</code>).
      </Feedback>
    );
  }

  const item = detailRes.data;

  return (
    <div className="stack">
      <p className="muted small">
        <Link to={`/announcements?club=${clubId}`}>← Announcements</Link>
        {clubName ? ` · ${clubName}` : null}
        {preview ? " · Preview" : null}
      </p>
      <PageState
        loading={detailRes.loading}
        error={detailRes.error}
        empty={!item}
        emptyMessage="Announcement not found."
      >
        {item && (
          <article className="panel stack">
            <div className="row">
              <h1>{item.title}</h1>
              <span className="badge">{item.visibility}</span>
              {item.status !== "published" && (
                <span className="badge badge--warn">{item.status}</span>
              )}
            </div>
            <p style={{ whiteSpace: "pre-wrap" }}>{item.body}</p>
            <p className="muted small">
              {item.published_at
                ? `Published ${new Date(item.published_at).toLocaleString()}`
                : `Created ${new Date(item.created_at).toLocaleString()}`}
              {item.correction_seq > 0 ? ` · Correction #${item.correction_seq}` : null}
            </p>
          </article>
        )}
      </PageState>
    </div>
  );
}
