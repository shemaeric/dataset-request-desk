import {
  ApiError,
  type DeskRequest,
  type EpisodePage,
  type EpisodeQuality,
  type RequestDetail,
  type RequestStatus,
  type User,
} from "./types";

const CSRF_COOKIE = "desk_csrf";
const CSRF_HEADER = "X-CSRF-Token";

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  return `${base}${path}`;
}

function csrfToken(): string | null {
  const parts = document.cookie.split("; ");
  const pair = parts.find((item) => item.startsWith(`${CSRF_COOKIE}=`));
  if (!pair) {
    return null;
  }
  return decodeURIComponent(pair.slice(CSRF_COOKIE.length + 1));
}

const fieldLabel: Record<string, string> = {
  task_name: "Task name",
  episodes_requested: "Episode count",
  deadline: "Deadline",
  notes: "Notes",
};

function validationText(detail: unknown[]): string | null {
  const lines: string[] = [];
  for (const item of detail) {
    if (typeof item !== "object" || item === null || !("msg" in item)) {
      continue;
    }
    const msg = item.msg;
    if (typeof msg !== "string" || !msg.trim()) {
      continue;
    }
    const loc = "loc" in item && Array.isArray(item.loc) ? item.loc : [];
    const name = loc.filter((part) => typeof part === "string" && part !== "body").at(-1);
    const field = typeof name === "string" ? (fieldLabel[name] ?? name) : "";
    const text = msg.replace(/^Value error,\s*/i, "");
    lines.push(field ? `${field}: ${text}` : text);
  }
  return lines.length > 0 ? lines.join(" ") : null;
}

function messageFromBody(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail)) {
      const text = validationText(detail);
      if (text) {
        return text;
      }
    }
  }
  if (status === 401) {
    return "Your session expired. Sign in again.";
  }
  if (status === 403) {
    return "You cannot do that.";
  }
  if (status === 404) {
    return "Request not found.";
  }
  if (status === 409) {
    return "That change is not allowed.";
  }
  if (status === 422) {
    return "Check the form and try again.";
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && method !== "HEAD" && path !== "/api/v1/auth/login") {
    const token = csrfToken();
    if (token) {
      headers.set(CSRF_HEADER, token);
    }
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && path !== "/api/v1/auth/login") {
      onUnauthorized?.();
    }
    throw new ApiError(response.status, messageFromBody(body, response.status));
  }

  return body as T;
}

export function login(email: string, password: string): Promise<User> {
  return request<User>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>("/api/v1/auth/logout", { method: "POST" });
}

export function currentUser(): Promise<User> {
  return request<User>("/api/v1/auth/me");
}

export function failureMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Could not reach the API";
  }
  if (error.status === 401) {
    return "Your session expired. Sign in again.";
  }
  if (error.status === 403) {
    return "You cannot do that.";
  }
  return error.message;
}

export function listRequests(): Promise<DeskRequest[]> {
  return request<DeskRequest[]>("/api/v1/requests");
}

export function createRequest(body: {
  task_name: string;
  episodes_requested: number;
  deadline: string;
  notes: string | null;
}): Promise<RequestDetail> {
  return request<RequestDetail>("/api/v1/requests", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRequest(requestId: number): Promise<RequestDetail> {
  return request<RequestDetail>(`/api/v1/requests/${requestId}`);
}

export function transitionRequest(
  requestId: number,
  status: RequestStatus,
): Promise<RequestDetail> {
  return request<RequestDetail>(`/api/v1/requests/${requestId}/transitions`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export function listEpisodes(query: {
  taskName: string;
  quality: EpisodeQuality | "";
  limit: number;
  offset: number;
}): Promise<EpisodePage> {
  const params = new URLSearchParams();
  if (query.taskName.trim()) {
    params.set("task_name", query.taskName.trim());
  }
  if (query.quality) {
    params.set("quality", query.quality);
  }
  params.set("limit", String(query.limit));
  params.set("offset", String(query.offset));
  return request<EpisodePage>(`/api/v1/episodes?${params}`);
}

export function assignEpisode(requestId: number, episodeId: number): Promise<void> {
  return request<void>(`/api/v1/requests/${requestId}/assignments`, {
    method: "POST",
    body: JSON.stringify({ episode_id: episodeId }),
  });
}

export function removeEpisode(requestId: number, episodeId: number): Promise<void> {
  return request<void>(`/api/v1/requests/${requestId}/assignments/${episodeId}`, {
    method: "DELETE",
  });
}
