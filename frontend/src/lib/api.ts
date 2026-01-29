const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://web:8000";

export function apiUrl(path: string): string {
  if (!path) {
    return API_BASE_URL;
  }
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

export type ApiError = Error & { status?: number; data?: unknown };

export function getCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop()?.split(";").shift() || null;
  }
  return null;
}

export async function ensureCsrfCookie(): Promise<void> {
  await fetch("/api/csrf/", {
    method: "GET",
    credentials: "include",
  });
}

type ApiRequestOptions = {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  csrf?: boolean;
  signal?: AbortSignal;
};

export async function apiRequest(
  path: string,
  options: ApiRequestOptions = {}
): Promise<Response> {
  const {
    method = "GET",
    body,
    headers = {},
    csrf = false,
    signal,
  } = options;

  if (csrf) {
    await ensureCsrfCookie();
  }

  const csrfToken = csrf ? getCookie("csrftoken") : null;
  const finalHeaders: Record<string, string> = { ...headers };
  let finalBody: BodyInit | undefined;

  if (body !== undefined) {
    finalHeaders["Content-Type"] =
      finalHeaders["Content-Type"] || "application/json";
    finalBody =
      typeof body === "string" ? body : JSON.stringify(body);
  }

  if (csrfToken) {
    finalHeaders["X-CSRFToken"] = csrfToken;
  }

  const response = await fetch(path, {
    method,
    headers: finalHeaders,
    body: finalBody,
    credentials: "include",
    signal,
  });

  if ((response.status === 401 || response.status === 403) && typeof window !== "undefined") {
    const currentPath = window.location.pathname;
    if (currentPath !== "/login" && currentPath !== "/download") {
      const query = window.location.search || "";
      const next = `${currentPath}${query}`;
      window.location.href = `/login?next=${encodeURIComponent(next)}`;
    }
  }

  return response;
}

async function buildApiError(response: Response): Promise<ApiError> {
  let data: unknown = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  const detailMessage =
    data &&
    typeof data === "object" &&
    "detail" in data &&
    typeof (data as { detail?: unknown }).detail === "string"
      ? (data as { detail?: string }).detail || ""
      : "";
  const message =
    detailMessage ||
    (data && typeof data === "object"
      ? JSON.stringify(data)
      : `Request failed: ${response.status}`);
  const error = new Error(message) as ApiError;
  error.status = response.status;
  error.data = data;
  return error;
}

export async function apiGetJson<T>(path: string): Promise<T> {
  const response = await apiRequest(path);
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return response.json();
}

export async function apiPostJson<T>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {}
): Promise<T> {
  const response = await apiRequest(path, {
    method: "POST",
    body,
    ...options,
  });
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return response.json();
}

export async function apiPutJson<T>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {}
): Promise<T> {
  const response = await apiRequest(path, {
    method: "PUT",
    body,
    ...options,
  });
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return response.json();
}

export async function apiPatchJson<T>(
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "method" | "body"> = {}
): Promise<T> {
  const response = await apiRequest(path, {
    method: "PATCH",
    body,
    ...options,
  });
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return response.json();
}

export async function apiDelete(
  path: string,
  options: Omit<ApiRequestOptions, "method" | "body"> = {}
): Promise<void> {
  const response = await apiRequest(path, { method: "DELETE", ...options });
  if (!response.ok) {
    throw await buildApiError(response);
  }
}
