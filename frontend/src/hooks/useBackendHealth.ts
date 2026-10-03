import { useEffect, useState } from "react";

import { api } from "../services/api";
import type { BackendStatus, HealthResponse } from "../types/health";

type HealthState = {
  status: BackendStatus;
  payload: HealthResponse | null;
  error: string | null;
};

export function useBackendHealth(): HealthState {
  const [state, setState] = useState<HealthState>({
    status: "loading",
    payload: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const payload = await api.getHealth();
        if (!cancelled) {
          setState({ status: "connected", payload, error: null });
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "unavailable",
            payload: null,
            error: error instanceof Error ? error.message : "Unknown error",
          });
        }
      }
    }

    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
