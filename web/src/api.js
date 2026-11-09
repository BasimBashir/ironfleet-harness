// The ONLY REST door to the harness (M8: the UI talks to the API + SSE, nothing else).
// Error envelope -> ApiError(code, message); POST/PUT/PATCH carry an Idempotency-Key;
// 202 comes back as pending:true so a screen never shows success before the backend confirms.
const BASE = "/api/v1";
const KEY = "ironfleet.token";

export class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// shortcut: token in sessionStorage (loopback, single operator); move to an httpOnly cookie with multi-user (M10)
export const getToken = () => globalThis.sessionStorage?.getItem(KEY) || "";
export const setToken = (t) => (t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY));

export async function request(method, path, body, { fetchImpl = fetch, token = getToken, raw = false } = {}) {
  const headers = { Authorization: `Bearer ${token()}` };
  if (method !== "GET" && method !== "DELETE") headers["Idempotency-Key"] = crypto.randomUUID();
  let payload;
  if (body !== undefined) {
    if (raw) payload = body;
    else { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  }
  const res = await fetchImpl(BASE + path, { method, headers, body: payload });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const e = data && typeof data === "object" ? data.error : null;
    if (res.status === 401) globalThis.dispatchEvent?.(new Event("ironfleet:logout"));
    throw new ApiError(res.status, e?.code || "http_error", e?.message || `HTTP ${res.status}`, e?.details);
  }
  return { status: res.status, data, pending: res.status === 202 };
}

export const get = (path) => request("GET", path).then((r) => r.data);
export const post = (path, body = {}) => request("POST", path, body);
export const put = (path, body = {}) => request("PUT", path, body);
export const patch = (path, body = {}) => request("PATCH", path, body);
export const del = (path) => request("DELETE", path);
// collections are {items, next_cursor} (04 §4 cursor paging)
export const page = (path, cursor) =>
  get(cursor ? `${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}` : path);
// document bytes for the S8 viewer (GET /documents/{id} is application/octet-stream)
export async function blob(path, { fetchImpl = fetch, token = getToken } = {}) {
  const res = await fetchImpl(BASE + path, { headers: { Authorization: `Bearer ${token()}` } });
  if (!res.ok) throw new ApiError(res.status, "http_error", `HTTP ${res.status}`);
  return res.blob();
}
// upload = raw body + ?filename= (M7 plan §0.1: no multipart)
export const upload = (path, file) =>
  request("POST", `${path}?filename=${encodeURIComponent(file.name)}`, file, { raw: true });
