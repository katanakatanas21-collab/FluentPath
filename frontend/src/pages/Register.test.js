import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Register from "./Register";
import TrialTest from "./TrialTest";

describe("student registration onboarding", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
    localStorage.clear();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "test-access-token", student: { role: "student" } }),
    });
  });

  afterEach(() => { global.fetch = originalFetch; });

  test("stores the returned session and starts the placement questions after registration", async () => {
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route path="/trial-test" element={<TrialTest />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(document.querySelector('[name="fullName"]'), { target: { value: "New Student" } });
    fireEvent.change(document.querySelector('[name="email"]'), { target: { value: "new.student@test.local" } });
    fireEvent.change(document.querySelector('[name="password"]'), { target: { value: "safe-test-password" } });
    fireEvent.change(document.querySelector('[name="dateOfBirth"]'), { target: { value: "2000-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "إنشاء الحساب وبدء الاختبار" }));

    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    expect(localStorage.getItem("fluentPathAccessToken")).toBe("test-access-token");
    expect(global.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/register",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("supports English registration and carries the language into placement", async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/register", state: { language: "en" } }]}>
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route path="/trial-test" element={<TrialTest />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Create a student account" })).toBeInTheDocument();
    fireEvent.change(document.querySelector('[name="fullName"]'), { target: { value: "New Student" } });
    fireEvent.change(document.querySelector('[name="email"]'), { target: { value: "new.student@test.local" } });
    fireEvent.change(document.querySelector('[name="password"]'), { target: { value: "safe-test-password" } });
    fireEvent.change(document.querySelector('[name="dateOfBirth"]'), { target: { value: "2000-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account and start test" }));

    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    expect(document.querySelector('[dir="ltr"]')).toBeInTheDocument();
  });
});
