import { ApiError, type User } from "./types";

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

function messageFromBody(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
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
