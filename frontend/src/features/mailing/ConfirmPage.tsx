import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { api, formatApiError } from "../../services/api";

export function ConfirmPage() {
  const [params] = useSearchParams();
  const token = params.get("token")?.trim() ?? "";
  const [status, setStatus] = useState<"idle" | "loading" | "ok" | "error">(
    token ? "loading" : "idle",
  );
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      setStatus("loading");
      try {
        const res = await api.post("/api/v1/mailing-list/confirm", {
          body: { token },
        });
        if (!cancelled) {
          setMessage(res.message);
          setStatus("ok");
        }
      } catch (err) {
        if (!cancelled) {
          setMessage(formatApiError(err));
          setStatus("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="stack">
      <section className="hero-block stack">
        <h1>Confirm subscription</h1>
        <p className="muted">Complete your CampusOS mailing list signup.</p>
      </section>

      {!token && (
        <Feedback tone="warn">
          Missing confirmation token. Open the link from your email, or return to the{" "}
          <Link to="/clubs">clubs directory</Link>.
        </Feedback>
      )}

      {token && status === "loading" && <Spinner label="Confirming…" />}

      {token && status === "ok" && (
        <Feedback tone="ok">
          {message ?? "Subscription confirmed."}
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <Link className="btn" to="/clubs">
              Browse clubs
            </Link>
          </div>
        </Feedback>
      )}

      {token && status === "error" && (
        <Feedback tone="danger">
          {message ?? "Could not confirm subscription."}
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <Link className="btn btn--ghost" to="/clubs">
              Back to clubs
            </Link>
          </div>
        </Feedback>
      )}
    </div>
  );
}
