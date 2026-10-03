import { StatusBadge } from "../components/ui/StatusBadge";
import { useBackendHealth } from "../hooks/useBackendHealth";
import { api } from "../services/api";

export function InitStatus() {
  const { status, payload, error } = useBackendHealth();

  return (
    <section className="init-panel" aria-labelledby="init-heading">
      <h2 id="init-heading">Project initialization</h2>
      <ul className="init-list">
        <li>
          <span className="init-list__label">Phase</span>
          <span>1 — foundation scaffold</span>
        </li>
        <li>
          <span className="init-list__label">Frontend</span>
          <span>React + TypeScript + Vite</span>
        </li>
        <li>
          <span className="init-list__label">Backend target</span>
          <span className="mono">{api.baseUrl}</span>
        </li>
        <li>
          <span className="init-list__label">Business modules</span>
          <span>Not implemented yet</span>
        </li>
      </ul>

      <div className="init-health">
        <h3>Backend connectivity</h3>
        <StatusBadge status={status} />
        {status === "connected" && payload && (
          <p className="init-health__detail mono">
            GET /api/v1/health → {JSON.stringify(payload)}
          </p>
        )}
        {status === "unavailable" && (
          <p className="init-health__detail">
            Could not reach the API. Start the backend on port 8000, then refresh.
            {error ? ` (${error})` : null}
          </p>
        )}
        {status === "loading" && (
          <p className="init-health__detail">Calling GET /api/v1/health…</p>
        )}
      </div>
    </section>
  );
}
