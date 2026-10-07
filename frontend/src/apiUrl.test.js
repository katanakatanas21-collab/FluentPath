const {
  validateProductionApiUrl,
  resolveProductionApiUrl,
  resolveDevelopmentApiUrl,
} = require("./apiUrl");
const buildGate = require("../scripts/validateApiUrl");

const SYNTHETIC = "https://api.synthetic-a2-test.invalid";

describe("production API origin validation", () => {
  test.each([
    ["unset", undefined],
    ["empty string", ""],
    ["whitespace only", "   "],
    ["the local backend fallback", "http://127.0.0.1:8000"],
    ["localhost over http", "http://localhost:8000"],
    ["a non-loopback origin over http", "http://api.example.test"],
    ["an ftp scheme", "ftp://api.example.test"],
    ["a protocol-relative value", "//api.example.test"],
    ["a bare hostname", "api.example.test"],
    ["a relative path", "/api"],
    ["free text", "not a url at all"],
    ["localhost over https", "https://localhost:8000"],
    ["127.0.0.1 over https", "https://127.0.0.1:8000"],
    ["0.0.0.0 over https", "https://0.0.0.0:8000"],
  ])("refuses %s", (_label, value) => {
    expect(validateProductionApiUrl(value)).toBeTruthy();
    expect(() => resolveProductionApiUrl(value)).toThrow();
  });

  test.each([
    ["a synthetic https origin", SYNTHETIC],
    ["a synthetic https origin with a path", `${SYNTHETIC}/base/`],
    ["a synthetic https origin with a trailing slash", `${SYNTHETIC}/`],
  ])("accepts %s", (_label, value) => {
    expect(validateProductionApiUrl(value)).toBeNull();
    expect(resolveProductionApiUrl(value)).toBe(value.replace(/\/+$/, ""));
  });

  test("trims surrounding whitespace before validating", () => {
    expect(resolveProductionApiUrl(`  ${SYNTHETIC}  `)).toBe(SYNTHETIC);
  });

  test("explains that no domain is hard-coded", () => {
    expect(validateProductionApiUrl(undefined)).toMatch(/hard-coded/i);
  });

  test("names the received protocol when https is required", () => {
    expect(validateProductionApiUrl("http://api.example.test")).toMatch(/https:\/\//);
  });

  // The build gate and the runtime guard are separate implementations in
  // separate runtimes, so they must be pinned to the same behaviour or the
  // build could pass a value the bundle later rejects (or the reverse).
  test.each([
    ["unset", undefined],
    ["empty string", ""],
    ["whitespace only", "   "],
    ["the local backend fallback", "http://127.0.0.1:8000"],
    ["localhost over http", "http://localhost:8000"],
    ["a non-loopback origin over http", "http://api.example.test"],
    ["an ftp scheme", "ftp://api.example.test"],
    ["a protocol-relative value", "//api.example.test"],
    ["a bare hostname", "api.example.test"],
    ["a relative path", "/api"],
    ["free text", "not a url at all"],
    ["localhost over https", "https://localhost:8000"],
    ["127.0.0.1 over https", "https://127.0.0.1:8000"],
    ["0.0.0.0 over https", "https://0.0.0.0:8000"],
    ["a synthetic https origin", SYNTHETIC],
    ["a synthetic https origin with a trailing slash", `${SYNTHETIC}/`],
  ])("build gate and runtime agree on %s", (_label, value) => {
    const runtimeSaysError = validateProductionApiUrl(value) !== null;
    const gateSaysError = buildGate.validationError(value) !== null;
    expect(gateSaysError).toBe(runtimeSaysError);
  });
});

describe("development API origin resolution", () => {
  test("falls back to the local backend so npm start keeps working", () => {
    expect(resolveDevelopmentApiUrl(undefined)).toBe("http://127.0.0.1:8000");
  });

  test("still honours an explicitly configured local origin", () => {
    expect(resolveDevelopmentApiUrl("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
  });

  test("does not require https outside production", () => {
    expect(resolveDevelopmentApiUrl("http://localhost:8000")).toBe("http://localhost:8000");
  });

  test("removes a trailing slash", () => {
    expect(resolveDevelopmentApiUrl(`${SYNTHETIC}/`)).toBe(SYNTHETIC);
  });
});

describe("module entry point", () => {
  const originalNodeEnv = process.env.NODE_ENV;
  const originalApiUrl = process.env.REACT_APP_API_URL;

  afterEach(() => {
    if (originalNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = originalNodeEnv;
    if (originalApiUrl === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = originalApiUrl;
    jest.resetModules();
  });

  test("uses the local fallback in a development build", () => {
    process.env.NODE_ENV = "development";
    delete process.env.REACT_APP_API_URL;
    jest.resetModules();
    expect(require("./apiUrl").API_URL).toBe("http://127.0.0.1:8000");
  });

  test("uses the configured origin in a production build", () => {
    process.env.NODE_ENV = "production";
    process.env.REACT_APP_API_URL = SYNTHETIC;
    jest.resetModules();
    expect(require("./apiUrl").API_URL).toBe(SYNTHETIC);
  });

  test("throws in a production build with no configured origin", () => {
    process.env.NODE_ENV = "production";
    delete process.env.REACT_APP_API_URL;
    jest.resetModules();
    expect(() => require("./apiUrl")).toThrow(/REACT_APP_API_URL is required/);
  });

  test("throws in a production build pointed at loopback", () => {
    process.env.NODE_ENV = "production";
    process.env.REACT_APP_API_URL = "http://127.0.0.1:8000";
    jest.resetModules();
    expect(() => require("./apiUrl")).toThrow();
  });
});