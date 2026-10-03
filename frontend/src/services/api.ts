/**
 * Typed CampusOS API client bound to generated OpenAPI paths/methods.
 * Callers cannot override response types with a free type argument.
 */
import type { components, paths } from "../types/openapi";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  body: unknown;

  constructor(
    status: number,
    code: string,
    message: string,
    fields: Record<string, string> = {},
    body: unknown = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.body = body;
  }
}

type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

type PathsWithMethod<M extends HttpMethod> = {
  [P in keyof paths]-?: paths[P] extends Record<M, unknown>
    ? M extends keyof paths[P]
      ? paths[P][M] extends never | undefined
        ? never
        : P
      : never
    : never;
}[keyof paths];

type Operation<P extends keyof paths, M extends HttpMethod> = P extends keyof paths
  ? M extends keyof paths[P]
    ? paths[P][M]
    : never
  : never;

type JsonBody<T> = T extends { content: { "application/json": infer B } } ? B : never;

type SuccessData<Op> = Op extends { responses: infer R }
  ? {
      [Code in keyof R]: Code extends 200 | 201
        ? JsonBody<R[Code]>
        : Code extends 204
          ? undefined
          : never;
    }[keyof R]
  : never;

type PathParams<Op> = Op extends { parameters: { path?: infer P } }
  ? P extends undefined
    ? undefined
    : P
  : undefined;

type QueryParams<Op> = Op extends { parameters: { query?: infer Q } }
  ? Q extends undefined
    ? undefined
    : Q
  : undefined;

type BodyParams<Op> = Op extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : Op extends { requestBody?: { content: { "application/json": infer B } } }
    ? B | undefined
    : undefined;

type HasPathParams<Op> = PathParams<Op> extends Record<string, unknown> ? true : false;
type HasQueryParams<Op> = QueryParams<Op> extends Record<string, unknown> ? true : false;
type HasRequiredBody<Op> = Op extends { requestBody: { content: { "application/json": unknown } } }
  ? true
  : false;

type ParamsBag<Op> = HasPathParams<Op> extends true
  ? HasQueryParams<Op> extends true
    ? { path: PathParams<Op>; query?: QueryParams<Op> }
    : { path: PathParams<Op>; query?: never }
  : HasQueryParams<Op> extends true
    ? { path?: never; query?: QueryParams<Op> }
    : { path?: never; query?: never };

type InitFor<Op> = (HasPathParams<Op> extends true
  ? { params: ParamsBag<Op> }
  : HasQueryParams<Op> extends true
    ? { params?: ParamsBag<Op> }
    : { params?: ParamsBag<Op> }) &
  (HasRequiredBody<Op> extends true
    ? { body: BodyParams<Op> }
    : BodyParams<Op> extends undefined
      ? { body?: undefined }
      : { body?: BodyParams<Op> });

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

function fillPath(
  template: string,
  pathParams?: Record<string, string | number | boolean | null | undefined>,
): string {
  let url = template;
  if (pathParams) {
    for (const [key, value] of Object.entries(pathParams)) {
      if (value === undefined || value === null) {
        throw new Error(`Missing path parameter: ${key}`);
      }
      url = url.replaceAll(`{${key}}`, encodeURIComponent(String(value)));
    }
  }
  if (url.includes("{")) {
    throw new Error(`Unresolved path parameters in ${url}`);
  }
  return url;
}

function appendQuery(
  url: string,
  query?: Record<string, string | number | boolean | null | undefined>,
): string {
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    qs.set(key, String(value));
  }
  const serialized = qs.toString();
  return serialized ? `${url}?${serialized}` : url;
}

async function requestJson<M extends HttpMethod, P extends PathsWithMethod<M>>(
  method: M,
  path: P,
  init?: InitFor<Operation<P, M>>,
): Promise<SuccessData<Operation<P, M>>> {
  const opInit = (init ?? {}) as {
    params?: {
      path?: Record<string, string | number | boolean | null | undefined>;
      query?: Record<string, string | number | boolean | null | undefined>;
    };
    body?: unknown;
  };
  const url = appendQuery(fillPath(String(path), opInit.params?.path), opInit.params?.query);
  const headers = new Headers();
  headers.set("Accept", "application/json");
  const upper = method.toUpperCase();
  let body: string | undefined;
  if (opInit.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opInit.body);
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(upper)) {
    const csrf = readCookie("campusos_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${url}`, {
      method: upper,
      headers,
      body,
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error — is the API running?");
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status})`;
    let fields: Record<string, string> = {};
    let parsedBody: unknown = null;
    try {
      parsedBody = await response.json();
      const parsed = parsedBody as {
        code?: string;
        message?: string;
        detail?: unknown;
        fields?: Record<string, string>;
        status?: string;
        duplicate?: boolean;
      };
      code = parsed.code ?? (parsed.duplicate ? "duplicate_checkin" : code);
      message = parsed.message ?? (parsed.duplicate ? "Ticket already checked in." : message);
      fields = parsed.fields ?? {};
      if (!parsed.message && Array.isArray(parsed.detail)) {
        message = parsed.detail
          .map((d: { loc?: unknown[]; msg?: string }) => {
            const loc = (d.loc ?? []).filter((p) => p !== "body").join(".");
            return loc ? `${loc}: ${d.msg}` : d.msg;
          })
          .join("; ");
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, code, message, fields, parsedBody);
  }

  if (response.status === 204) {
    return undefined as SuccessData<Operation<P, M>>;
  }
  return (await response.json()) as SuccessData<Operation<P, M>>;
}

export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const fieldMsg = Object.entries(err.fields)
      .map(([k, v]) => `${k}: ${v}`)
      .join("; ");
    return fieldMsg ? `${err.message} (${fieldMsg})` : err.message;
  }
  return "Something went wrong";
}

type GetInit<P extends PathsWithMethod<"get">> = InitFor<Operation<P, "get">>;
type PostInit<P extends PathsWithMethod<"post">> = InitFor<Operation<P, "post">>;
type PatchInit<P extends PathsWithMethod<"patch">> = InitFor<Operation<P, "patch">>;

function get<P extends PathsWithMethod<"get">>(
  path: P,
  ...args: HasPathParams<Operation<P, "get">> extends true
    ? [init: GetInit<P>]
    : [init?: GetInit<P>]
): Promise<SuccessData<Operation<P, "get">>> {
  return requestJson("get", path, args[0]);
}

function post<P extends PathsWithMethod<"post">>(
  path: P,
  ...args: HasRequiredBody<Operation<P, "post">> extends true
    ? [init: PostInit<P>]
    : HasPathParams<Operation<P, "post">> extends true
      ? [init: PostInit<P>]
      : [init?: PostInit<P>]
): Promise<SuccessData<Operation<P, "post">>> {
  return requestJson("post", path, args[0]);
}

function patch<P extends PathsWithMethod<"patch">>(
  path: P,
  ...args: [init: PatchInit<P>]
): Promise<SuccessData<Operation<P, "patch">>> {
  return requestJson("patch", path, args[0]);
}

/** Multipart receipt upload (not JSON — outside typed post helpers). */
async function uploadExpenseReceipt(
  clubId: string,
  expenseId: string,
  file: File,
): Promise<components["schemas"]["ExpenseAttachmentOut"]> {
  const csrf = readCookie("campusos_csrf");
  const headers = new Headers();
  headers.set("Accept", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const body = new FormData();
  body.append("file", file);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/api/v1/clubs/${encodeURIComponent(clubId)}/expenses/${encodeURIComponent(expenseId)}/attachments`,
      { method: "POST", headers, body, credentials: "include" },
    );
  } catch {
    throw new ApiError(0, "network_error", "Network error — is the API running?");
  }
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status})`;
    let fields: Record<string, string> = {};
    try {
      const parsed = (await response.json()) as {
        code?: string;
        message?: string;
        fields?: Record<string, string>;
      };
      code = parsed.code ?? code;
      message = parsed.message ?? message;
      fields = parsed.fields ?? {};
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, code, message, fields);
  }
  return (await response.json()) as components["schemas"]["ExpenseAttachmentOut"];
}

function receiptDownloadUrl(clubId: string, expenseId: string, attachmentId: string): string {
  return `${API_BASE_URL}/api/v1/clubs/${encodeURIComponent(clubId)}/expenses/${encodeURIComponent(expenseId)}/attachments/${encodeURIComponent(attachmentId)}/download`;
}

export const api = {
  baseUrl: API_BASE_URL,
  get,
  post,
  patch,
  uploadExpenseReceipt,
  receiptDownloadUrl,
};
