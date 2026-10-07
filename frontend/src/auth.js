import { API_URL } from "./apiUrl";

export { API_URL };
const TOKEN_KEY = "fluentPathAccessToken";

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthSession(accessToken) {
  if (accessToken) localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.removeItem("fluentPathStudent");
}

export function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("fluentPathStudent");
}

export async function authFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { ...options, headers });
}

export async function logout() {
  try {
    if (getAccessToken()) await authFetch("/api/logout", { method: "POST" });
  } finally {
    clearAuthSession();
  }
}
