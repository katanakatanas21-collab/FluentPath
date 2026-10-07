#!/usr/bin/env node
// Build-time gate for the backend origin a production bundle will use.
//
// A throw inside the application bundle is not a build failure: webpack
// compiles the module without executing it, so an invalid value would ship and
// only surface as a blank page in the browser. This script runs in Node before
// the bundler, so an unusable REACT_APP_API_URL stops the build outright.
//
// The matching runtime guard lives in src/apiUrl.js. The two deliberately
// restate the same rules because they execute in different runtimes and this
// file cannot import the ES module the bundler consumes. src/apiUrl.test.js
// asserts that the two agree.

const DEVELOPMENT_API_FALLBACK = "http://127.0.0.1:8000";
const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"]);

function validationError(configured) {
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

  if (LOOPBACK_HOSTNAMES.has(parsed.hostname.toLowerCase())) {
    return (
      "REACT_APP_API_URL must not point at a loopback host in a production build. " +
      `Received "${parsed.hostname}".`
    );
  }

  return null;
}

function main() {
  const configured = (process.env.REACT_APP_API_URL || "").trim();
  const error = validationError(configured);
  if (error) {
    process.stderr.write(`\nFluent Path production build refused.\n\n  ${error}\n\n`);
    process.stderr.write(
      `  Local development is unaffected: with no value set, "npm start" uses ` +
        `${DEVELOPMENT_API_FALLBACK}.\n\n`,
    );
    process.exit(1);
  }
  process.stdout.write(`Fluent Path production API origin accepted: ${configured}\n`);
}

if (require.main === module) {
  main();
}

module.exports = { validationError, DEVELOPMENT_API_FALLBACK, LOOPBACK_HOSTNAMES };