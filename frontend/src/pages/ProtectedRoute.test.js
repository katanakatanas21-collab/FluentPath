import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import ProtectedRoute from "./ProtectedRoute";

function PlacementDestination() {
  const location = useLocation();
  return <p>{location.state?.autoStartPlacementTest ? "Placement test started" : "Placement test intro"}</p>;
}

function renderProtected(initialPath, user, roles = ["student"]) {
  localStorage.setItem("fluentPathAccessToken", "test-token");
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => user });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/student-dashboard" element={<ProtectedRoute roles={roles}><p>Student dashboard</p></ProtectedRoute>} />
        <Route path="/trial-test" element={<ProtectedRoute roles={["student"]}><PlacementDestination /></ProtectedRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

function PlacementThenDashboard() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <ProtectedRoute roles={["student"]}>
      {location.pathname === "/trial-test" ? <><p>Placement test started</p><button onClick={() => navigate("/student-dashboard")}>Finish placement</button></> : <p>Student dashboard</p>}
    </ProtectedRoute>
  );
}

describe("placement access gate", () => {
  let originalFetch;
  beforeEach(() => { originalFetch = global.fetch; localStorage.clear(); });
  afterEach(() => { global.fetch = originalFetch; });

  test("redirects an authenticated but unplaced student from protected pages to the test", async () => {
    renderProtected("/student-dashboard", { id: "new", role: "student", level: null, testCompletedAt: null });
    expect(await screen.findByText("Placement test started")).toBeInTheDocument();
  });

  test("preserves access for placed existing students", async () => {
    renderProtected("/student-dashboard", { id: "existing", role: "student", level: "A2 - B1", testCompletedAt: null });
    expect(await screen.findByText("Student dashboard")).toBeInTheDocument();
  });

  test("preserves teacher authorization behavior", async () => {
    renderProtected("/student-dashboard", { id: "teacher", role: "teacher", level: null }, ["student"]);
    expect(await screen.findByText(/Access unavailable/)).toBeInTheDocument();
  });

  test("refreshes the user before enforcing placement when the path changes", async () => {
    const profiles = [
      { id: "new", role: "student", level: null, testCompletedAt: null },
      { id: "new", role: "student", level: "A2 - B1", testCompletedAt: "2026-09-27T12:00:00Z" },
    ];
    localStorage.setItem("fluentPathAccessToken", "test-token");
    global.fetch = jest.fn().mockImplementation(async () => ({ ok: true, status: 200, json: async () => profiles.shift() }));
    render(
      <MemoryRouter initialEntries={["/trial-test"]}>
        <Routes><Route path="*" element={<PlacementThenDashboard />} /></Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Finish placement" }));
    expect(await screen.findByText("Student dashboard")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});
