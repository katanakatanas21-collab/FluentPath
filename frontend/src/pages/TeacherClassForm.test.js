import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { authFetch } from "../auth";
import TeacherClassForm from "./TeacherClassForm";

jest.mock("../auth", () => ({ authFetch: jest.fn() }));

function jsonResponse(payload, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) });
}

test("teacher sees server Zoom configuration state and automatic meeting option", async () => {
  authFetch.mockImplementation((path) => {
    if (path === "/api/teacher/courses") return jsonResponse({ courses: [] });
    if (path === "/api/teacher/students") return jsonResponse({ students: [] });
    if (path === "/api/teacher/classes") return jsonResponse({ classes: [] });
    return jsonResponse({ zoomConfigured: false });
  });

  render(<MemoryRouter initialEntries={["/teacher-classes/new"]}><Routes><Route path="/teacher-classes/new" element={<TeacherClassForm />} /></Routes></MemoryRouter>);
  const provider = await screen.findByLabelText("مزود الاجتماع");
  await userEvent.selectOptions(provider, "zoom");
  expect(await screen.findByText(/Zoom غير مُعد على الخادم/)).toBeInTheDocument();
  expect(screen.queryByLabelText("رابط انضمام المعلم (اختياري)")).not.toBeInTheDocument();
  expect(authFetch).toHaveBeenCalledWith("/api/teacher/meeting-options");
  await waitFor(() => expect(screen.getByRole("button", { name: "حفظ الحصة" })).toBeEnabled());
});

test("teacher sees when Zoom is configured on the server", async () => {
  authFetch.mockImplementation((path) => {
    if (path === "/api/teacher/courses") return jsonResponse({ courses: [] });
    if (path === "/api/teacher/students") return jsonResponse({ students: [] });
    if (path === "/api/teacher/classes") return jsonResponse({ classes: [] });
    return jsonResponse({ zoomConfigured: true });
  });

  render(<MemoryRouter initialEntries={["/teacher-classes/new"]}><Routes><Route path="/teacher-classes/new" element={<TeacherClassForm />} /></Routes></MemoryRouter>);
  await userEvent.selectOptions(await screen.findByLabelText("مزود الاجتماع"), "zoom");
  expect(await screen.findByText(/Zoom متصل/)).toBeInTheDocument();
  expect(screen.queryByText(/Zoom غير مُعد/)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "حفظ الحصة" })).toBeEnabled());
});
