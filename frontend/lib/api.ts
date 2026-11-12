import type { components, paths } from "./openapi";

export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];
export type Filters = Schema<"CatalogFilters">;
export type Niche = Schema<"Niche">;

type Method = "get" | "post" | "patch" | "delete";
type Route<M extends Method> = {
  [P in keyof paths]: paths[P][M] extends { responses: unknown } ? P : never
}[keyof paths];

type Operation<M extends Method, P extends Route<M>> = paths[P][M];
type Query<O> = O extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;
type Path<O> = O extends { parameters: { path: infer P } } ? P : never;
type Body<O> = O extends { requestBody: { content: { "application/json": infer B } } } ? B : never;
type Result<R> = R extends { content: { "application/json": infer T } } ? T : void;
type Success<O> = O extends { responses: infer R } ? Result<R[Extract<keyof R, 200 | 201 | 202 | 204>]> : never;
type Options<O> = {
  signal?: AbortSignal;
  query?: Query<O>;
  csrf?: string;
  key?: string;
} & ([Path<O>] extends [never] ? { path?: never } : { path: Path<O> })
  & ([Body<O>] extends [never] ? { body?: never } : { body: Body<O> });

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, readonly requestId?: string) {
    super(code);
  }
}

export async function api<M extends Method, P extends Route<M>>(
  method: M, route: P, options: Options<Operation<M, P>>,
): Promise<Success<Operation<M, P>>> {
  const path = route.replace(/\{([^}]+)\}/g, (_, name: string) =>
    encodeURIComponent((options.path as Record<string, string>)[name]),
  );
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const headers = new Headers({ Accept: "application/json" });
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.csrf) headers.set("X-CSRF-Token", options.csrf);
  if (options.key) headers.set("Idempotency-Key", options.key);

  const response = await fetch(`/api/v1${path}${params.size ? `?${params}` : ""}`, {
    method: method.toUpperCase(),
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (!response.ok) {
    if (response.status === 401 && !(route === "/session" && method !== "delete")) {
      window.dispatchEvent(new Event("enot:session-expired"));
    }
    const payload: Partial<Schema<"Error">> = await response.json().catch(() => null) ?? {};
    throw new ApiError(response.status, payload.code ?? "http_error",
      payload.request_id ?? response.headers.get("X-Request-ID") ?? undefined);
  }
  if (response.status === 204) return undefined as Success<Operation<M, P>>;
  return response.json();
}

export function selection(niches: Niche[]): Schema<"Selection"> | undefined {
  const first = niches[0];
  if (!first || first.score.model_version !== "2.0-pilot") return;
  if (niches.some(({ dataset_id, score }) =>
    dataset_id !== first.dataset_id || score.model_version !== first.score.model_version)) return;
  return { dataset_id: first.dataset_id, model_version: first.score.model_version, niche_ids: niches.map(({ id }) => id) };
}
