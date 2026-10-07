import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AiTeacher from "./AiTeacher";
import { authFetch } from "../auth";

jest.mock("../auth", () => ({ authFetch: jest.fn() }));

const jsonResponse = (payload, ok = true, status = 200) => ({ ok, status, json: async () => payload });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(async (path) => path === "/api/me/ai/sessions"
    ? jsonResponse({ sessions: [] })
    : jsonResponse({ unreadCount: 0 }));
});

test("shows bilingual practice modes and a clear configuration state when no provider is configured", async () => {
  render(<MemoryRouter><AiTeacher /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "اختر طريقة التدريب" })).toBeInTheDocument();
  expect(document.querySelector(".ai-speech-note")).toHaveTextContent("التدريب الصوتي غير متاح بعد؛ استخدم الإجابات النصية فقط.");

  authFetch.mockImplementation(async (path, options) => {
    if (path === "/api/me/ai/sessions" && options?.method === "POST") return jsonResponse({ detail: "AI_TEACHER_NOT_CONFIGURED" }, false, 503);
    return path === "/api/me/ai/sessions" ? jsonResponse({ sessions: [] }) : jsonResponse({ unreadCount: 0 });
  });
  fireEvent.click(screen.getByRole("button", { name: /المفردات/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("اطلب من مسؤول المنصة إضافة OPENAI_API_KEY");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(await screen.findByRole("heading", { name: "AI Teacher" })).toBeInTheDocument();
  expect(document.querySelector(".ai-speech-note")).toHaveTextContent("Voice practice is not available yet. Text responses only.");
});

test("renders persisted session history and feedback returned by the API", async () => {
  const session = { id: "session-1", mode: "writing", cefr_level: "A2", status: "completed", created_at: "2026-09-27T10:00:00+00:00" };
  authFetch.mockImplementation(async (path) => {
    if (path === "/api/me/ai/sessions") return jsonResponse({ sessions: [session] });
    if (path === "/api/me/ai/sessions/session-1") return jsonResponse({ session, messages: [{ id: "m1", role: "assistant", content: "Write about your day.", feedback: "Use past tense verbs.", score: 80, corrections: ["I go → I went"], next_step: "Try one more sentence.", xp_awarded: 10 }] });
    return jsonResponse({ unreadCount: 0 });
  });
  render(<MemoryRouter><AiTeacher /></MemoryRouter>);
  await screen.findByText("الكتابة");
  fireEvent.click(screen.getByText("جلساتك الأخيرة").closest("aside").querySelector("button"));
  expect(await screen.findByText("Write about your day.")).toBeInTheDocument();
  expect(screen.getByText("Use past tense verbs.")).toBeInTheDocument();
  expect(screen.getByText("I go → I went")).toBeInTheDocument();
  expect(document.querySelector(".ai-xp-chip")).toHaveTextContent("+10 XP مكتسبة");
  await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/api/me/ai/sessions/session-1"));
});
