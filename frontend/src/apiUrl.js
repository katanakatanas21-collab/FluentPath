// Resolves the backend origin the app talks to.
//
// Outside production the local development backend is used unless the owner
// configures something else, which keeps the local workflow working. A
// production build has no such fallback: shipping a bundle that silently points
// at a developer's own machine is the failure this module prevents, so an
// unusable value stops the build instead.
//
// The production/development split is written as a direct comparison against
// process.env.NODE_ENV so the bundler can fold it. That is what removes the
// development fallback literal from a production bundle entirely, rather than
// leaving unreachable dead code behind.

const LOOPBACK_HOSTNAMES = ["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"];

function stripTrailingSlashes(value) {
  return value.replace(/\/+$/, "");
}

export function validateProductionApiUrl(configured) {
  if (!configured) {
    return (
      "REACT_APP_API_URL is required for a production build. Set it to the absolute " +
      "https:// origin of the Fluent Path backend. No production domain is hard-coded " +
      "in this project; the deployment owner must supply the value at build time."
    );
  }

  let parsed;
  try {
    parsed = new URL(configured);
  } catch {
    return (
      "REACT_APP_API_URL must be an absolute URL such as https://your-backend.example. " +
      "Received a value that is not an absolute URL."
    );
  }

  if (parsed.protocol !== "https:") {
    return (
      "REACT_APP_API_URL must use https:// in a production build. Received the protocol " +
      `"${parsed.protocol.replace(":", "")}://".`
    );
  }

  if (!parsed.hostname) {
    return "REACT_APP_API_URL must include a hostname such as https://your-backend.example.";
  }

  if (LOOPBACK_HOSTNAMES.includes(parsed.hostname.toLowerCase())) {
    return (
      "REACT_APP_API_URL must not point at a loopback host in a production build. " +
      `Received "${parsed.hostname}".`
    );
  }

  return null;
}

export function resolveProductionApiUrl(configured) {
  const trimmed = (configured || "").trim();
  const error = validateProductionApiUrl(trimmed);
  if (error) {
    throw new Error(error);
  }
  return stripTrailingSlashes(trimmed);
}

export function resolveDevelopmentApiUrl(configured) {
  return stripTrailingSlashes((configured || "").trim() || "http://127.0.0.1:8000");
}

export const API_URL =
  process.env.NODE_ENV === "production"
    ? resolveProductionApiUrl(process.env.REACT_APP_API_URL)
    : resolveDevelopmentApiUrl(process.env.REACT_APP_API_URL);