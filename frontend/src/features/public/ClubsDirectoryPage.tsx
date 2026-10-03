import { Link } from "react-router-dom";

import { PageState } from "../../components/ui/Feedback";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { api } from "../../services/api";
export function ClubsDirectoryPage() {
  const { data, loading, error } = useAsyncResource(
    () => api.get("/api/v1/clubs"),
    [],
    { cacheKeys: ["clubs"] },
  );

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Clubs</h1>
        <p className="muted">Browse campus organizations and open a club page.</p>
      </div>
      <PageState loading={loading} error={error} empty={!data?.length} emptyMessage="No clubs yet.">
        <div className="stack">
          {(data ?? []).map((club) => (
            <article key={club.id} className="panel row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{club.name}</h2>
                <p className="muted">{club.description || "No description."}</p>
              </div>
              <Link className="btn" to={`/clubs/${club.slug}`}>
                Open
              </Link>
            </article>
          ))}
        </div>
      </PageState>
    </div>
  );
}
