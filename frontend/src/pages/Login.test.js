import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Login from "./Login";
import TrialTest from "./TrialTest";

describe("login onboarding destination", () => {
  let originalFetch;
  beforeEach(() => { originalFetch = global.fetch; localStorage.clear(); });
  afterEach(() => { global.fetch = originalFetch; });

  test("sends a newly registered but unplaced student into the placement test", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-student-token",
        user: { id: "new-student", role: "student", level: null, testCompletedAt: null },
      }),
    });
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/trial-test" element={<TrialTest />} />
          <Route path="/student-dashboard" element={<p>Student dashboard</p>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText("البريد الإلكتروني"), { target: { value: "new.student@test.local" } });
    fireEvent.change(screen.getByLabelText("كلمة المرور"), { target: { value: "safe-test-password" } });
    fireEvent.click(screen.getByRole("button", { name: "دخول" }));

    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    expect(localStorage.getItem("fluentPathAccessToken")).toBe("new-student-token");
  });

  test("sends a placed student to the dashboard", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "placed-student-token",
        user: { id: "placed-student", role: "student", level: "A2 - B1", testCompletedAt: null },
      }),
    });
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/trial-test" element={<p>Placement test</p>} />
          <Route path="/student-dashboard" element={<p>Student dashboard</p>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("البريد الإلكتروني"), { target: { value: "placed.student@test.local" } });
    fireEvent.change(screen.getByLabelText("كلمة المرور"), { target: { value: "safe-test-password" } });
    fireEvent.click(screen.getByRole("button", { name: "دخول" }));
    expect(await screen.findByText("Student dashboard")).toBeInTheDocument();
  });
});
