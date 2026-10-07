import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { authFetch } from "../auth";
import TrialTest from "./TrialTest";

jest.mock("../auth", () => ({ authFetch: jest.fn() }));

describe("placement test completion", () => {
  beforeEach(() => {
    authFetch.mockResolvedValue({ ok: true, json: async () => ({ success: true, result: { score: 5, totalQuestions: 5, level: "B2 - C1" } }) });
  });

  afterEach(() => jest.clearAllMocks());

  test("saves the result and offers the student dashboard", async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/trial-test", state: { autoStartPlacementTest: true } }]}>
        <Routes>
          <Route path="/trial-test" element={<TrialTest />} />
          <Route path="/student-dashboard" element={<p>Student dashboard</p>} />
        </Routes>
      </MemoryRouter>,
    );

    const answers = [
      "She goes to school every day.",
      "Difficult",
      "have learned",
      "would study",
      "He has been working here since 2022.",
    ];
    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    for (let index = 0; index < answers.length; index += 1) {
      fireEvent.click(screen.getByRole("button", { name: answers[index] }));
      fireEvent.click(screen.getByRole("button", { name: index === answers.length - 1 ? "إنهاء الاختبار" : "السؤال التالي" }));
    }

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/api/test-results", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ answers: [1, 1, 2, 2, 0] }),
    })));
    expect(await screen.findByText("تم حفظ نتيجتك بنجاح.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "لوحة الطالب" }));
    expect(await screen.findByText("Student dashboard")).toBeInTheDocument();
  });

  test("keeps the placement test usable in English and Arabic", async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/trial-test", state: { autoStartPlacementTest: true, language: "en" } }]}>
        <Routes><Route path="/trial-test" element={<TrialTest />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    expect(document.querySelector('[dir="ltr"]')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(await screen.findByText("Question 1 of 5")).toBeInTheDocument();
    expect(document.querySelector('[dir="rtl"]')).toBeInTheDocument();
  });
});
