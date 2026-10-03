export type HealthResponse = {
  status: string;
  service: string;
};

export type BackendStatus = "loading" | "connected" | "unavailable";
