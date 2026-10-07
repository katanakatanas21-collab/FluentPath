describe("backend API configuration", () => {
  const originalApiUrl = process.env.REACT_APP_API_URL;
  const originalFetch = global.fetch;

  afterEach(() => {
    if (originalApiUrl === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = originalApiUrl;
    global.fetch = originalFetch;
    jest.resetModules();
  });

  test("uses the configured backend origin and removes a trailing slash", async () => {
    process.env.REACT_APP_API_URL = "https://api.example.test/";
    jest.resetModules();
    global.fetch = jest.fn().mockResolvedValue({ ok: true });
    const { API_URL, authFetch } = require("./auth");

    expect(API_URL).toBe("https://api.example.test");
    await authFetch("/api/health");

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.test/api/health",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });
});
