import { z } from "zod";
import type {
  Case,
  CaseSummary,
  ReviewListItem,
  Stats,
  DecisionRequest,
  GmailStatus,
  GmailSyncRequest,
  GmailSyncResponse,
} from "../shared/types";
import {
  caseSchema,
  errorSchema,
  reviewListSchema,
  statsSchema,
  summarySchema,
  gmailStatusSchema,
  gmailSyncResponseSchema,
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
  decide(decision: DecisionRequest): Promise<Case>;
  documentUrl(id: string): string;
  gmailStatus(signal?: AbortSignal): Promise<GmailStatus>;
  gmailSync(req?: GmailSyncRequest, signal?: AbortSignal): Promise<GmailSyncResponse>;
  composeMockEmail(formData: FormData, signal?: AbortSignal): Promise<Case>;
}
export async function request<T>(
  url: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
  expectedStatus?: number,
): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    signal: init.signal ?? AbortSignal.timeout(12000),
    headers: {
      ...(init.body && !isFormData ? { "Content-Type": "application/json" } : {}),
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
  if (expectedStatus && response.status !== expectedStatus)
    throw new RequestError(
      502,
      "INVALID_PAYLOAD",
      "Unexpected acceptance response; refetch before deciding again.",
    );
  const parsed = schema.safeParse(body);
  if (!parsed.success)
    throw new RequestError(
      502,
      "INVALID_PAYLOAD",
      "API data failed Shared Contract v2.1.2 validation. Last valid data is retained.",
    );
  return parsed.data;
}
function httpApi(base: string): CaseApi {
  return {
    list: (filters = {}, signal) => {
      const q = new URLSearchParams(
        Object.entries({ limit: "1000", ...filters }).filter(([, v]) => v !== ""),
      );
      return request(`${base}/cases?${q}`, z.array(summarySchema), { signal });
    },
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
    decide: (decision) =>
      request(
        `${base}/reviews/${encodeURIComponent(decision.review_id)}/decision`,
        caseSchema,
        { method: "POST", body: JSON.stringify(decision) },
        202,
      ),
    documentUrl: (id) => `${base}/documents/${encodeURIComponent(id)}/content`,
    gmailStatus: (signal) =>
      request(`${base}/inbox/gmail/status`, gmailStatusSchema, { signal }),
    gmailSync: (req = {}, signal) =>
      request(`${base}/inbox/gmail/sync`, gmailSyncResponseSchema, {
        method: "POST",
        body: JSON.stringify(req),
        signal,
      }),
    composeMockEmail: async (formData, signal) => {
      const response = await fetch(`${base}/inbox/compose`, {
        method: "POST",
        body: formData,
        signal: signal ?? AbortSignal.timeout(30000),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        const error = errorSchema.safeParse(body);
        throw new RequestError(
          response.status,
          error.success ? error.data.error.code : "INTERNAL",
          error.success
            ? error.data.error.message
            : "Failed to compose and ingest mock email.",
        );
      }
      const parsed = caseSchema.safeParse(body);
      if (!parsed.success)
        throw new RequestError(
          502,
          "INVALID_PAYLOAD",
          "Generated case failed contract validation.",
        );
      return parsed.data;
    },
  };
}
// Both implementations cross the same HTTP + validation boundary. No fixture imports in UI.
export const createSimulatedApi = () => httpApi("/api/v1");
export const createLiveApi = (base = "/api/v1") => httpApi(base);
export const isSimulation =
  import.meta.env.VITE_API_MODE !== "live" &&
  import.meta.env.MODE !== "live";
export let hostedDeployment = false;
export let readOnlySample = false;
export function setHostedContext(hosted: boolean, sample: boolean) {
  hostedDeployment = hosted;
  readOnlySample = sample;
}
export const api = isSimulation
  ? createSimulatedApi()
  : createLiveApi(import.meta.env.VITE_API_BASE ?? "/api/v1");
export const demoControl = (
  action: "reset" | "advance" | "fault" | "decision-fault",
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
          contract: z.literal("2.1.2"),
          milestone: z.enum(["F1", "F2"]),
          actor_id: z.literal("demo-guest"),
          decision_fault: z.enum(["none", "lost-response", "fail-resumption"]),
          fault: z.enum(["none", "outage", "slow", "denied"]),
          hosted: z.boolean().optional(),
          telegram_url: z.string().url().optional(),
          sample: z.boolean().optional(),
          dataset_size: z.number().optional(),
        }),
      )
    : Promise.resolve(null);
