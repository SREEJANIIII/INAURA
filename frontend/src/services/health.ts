import { apiFetch } from "./api";

export type HealthResponse = {
  status: string;
  service: string;
  message: string;
};

export function checkHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}
