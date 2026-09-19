import { z } from "zod";
import type { Case, CaseSummary, ReviewListItem, Stats } from "../shared/types";
import {
  caseSchema,
  errorSchema,
  reviewListSchema,
  statsSchema,
  summarySchema,
} from "../shared/validation";
export type Filters = {
  workflow_status?: string;
  category?: string;
  final_status?: string;
  has_open_review?: string;
};
export class RequestError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export interface CaseApi {
  list(filters?: Filters, signal?: AbortSignal): Promise<CaseSummary[]>;
  detail(id: string, signal?: AbortSignal): Promise<Case>;
  stats(signal?: AbortSignal): Promise<Stats>;
  reviews(signal?: AbortSignal): Promise<ReviewListItem[]>;
  create(emailId: string): Promise<Case>;
  reprocess(id: string): Promise<Case>;
  documentUrl(id: string): string;
}
export async function request<T>(
  url: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    signal: init.signal ?? AbortSignal.timeout(12000),
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = errorSchema.safeParse(body);
    throw new RequestError(
      response.status,
      error.success ? error.data.error.code : "INTERNAL",
      error.success
        ? error.data.error.message
        : "The API returned an unreadable error.",
    );
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success)
    throw new RequestError(
      502,
      "INVALID_PAYLOAD",
      "API data failed Shared Contract v2.1.1 validation. Last valid data is retained.",
    );
  return parsed.data;
}
function httpApi(base: string): CaseApi {
  return {
    list: (filters = {}, signal) =>
      request(
        `${base}/cases?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== ""))}`,
        z.array(summarySchema),
        { signal },
      ),
    detail: (id, signal) =>
      request(`${base}/cases/${encodeURIComponent(id)}`, caseSchema, {
        signal,
      }),
    stats: (signal) => request(`${base}/stats`, statsSchema, { signal }),
    reviews: (signal) =>
      request(`${base}/reviews`, reviewListSchema, { signal }),
    create: (emailId) =>
      request(`${base}/cases`, caseSchema, {
        method: "POST",
        body: JSON.stringify({ email_id: emailId }),
      }),
    reprocess: (id) =>
      request(`${base}/cases/${encodeURIComponent(id)}/reprocess`, caseSchema, {
        method: "POST",
        body: "{}",
      }),
    documentUrl: (id) => `${base}/documents/${encodeURIComponent(id)}/content`,
  };
}
// Both implementations cross the same HTTP + validation boundary. No fixture imports in UI.
export const createSimulatedApi = () => httpApi("/api/v1");
export const createLiveApi = (base = "/api/v1") => httpApi(base);
export const isSimulation = import.meta.env.VITE_API_MODE !== "live";
export const api = isSimulation
  ? createSimulatedApi()
  : createLiveApi(import.meta.env.VITE_API_BASE ?? "/api/v1");
export const demoControl = (
  action: "reset" | "advance" | "fault",
  body: object = {},
) =>
  request(`/api/demo/${action}`, z.object({ ok: z.literal(true) }), {
    method: "POST",
    body: JSON.stringify(body),
  });
export const initialize = () =>
  isSimulation
    ? request(
        "/api/demo/config",
        z.object({
          mode: z.literal("synthetic"),
          contract: z.literal("2.1.1"),
          milestone: z.literal("F0"),
          fault: z.enum(["none", "outage", "slow", "denied"]),
        }),
      )
    : Promise.resolve(null);
