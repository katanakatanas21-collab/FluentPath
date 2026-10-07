import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { authFetch } from "../auth";

const questions = [
  {
    question: "Choose the correct sentence:",
    options: [
      "She go to school every day.",
      "She goes to school every day.",
      "She going to school every day.",
      "She gone to school every day.",
    ],
  },
  {
    question: "What is the opposite of 'easy'?",
    options: ["Simple", "Difficult", "Fast", "Small"],
  },
  {
    question: "Complete: I _____ English for three years.",
    options: ["learn", "learned", "have learned", "learning"],
  },
  {
    question: "Choose the correct option: If I had more time, I _____ more.",
    options: ["study", "will study", "would study", "studied"],
  },
  {
    question: "Which sentence is grammatically correct?",
    options: [
      "He has been working here since 2022.",
      "He is working here since 2022.",
      "He have been working here since 2022.",
      "He worked here since 2022.",
    ],
  },
];

function TrialTest() {
  const location = useLocation();
  const navigate = useNavigate();
  const autoStart = Boolean(location.state?.autoStartPlacementTest);
  const [language, setLanguage] = useState(location.state?.language === "en" ? "en" : "ar");
  const ar = language === "ar";
  const [started, setStarted] = useState(autoStart);
  const [currentQuestion, setCurrentQuestion] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState(null);
  const [score, setScore] = useState(0);
  const [level, setLevel] = useState("");
  const [answers, setAnswers] = useState([]);
  const [finished, setFinished] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    if (autoStart) navigate(location.pathname, { replace: true, state: null });
  }, [autoStart, location.pathname, navigate]);

  const handleStart = () => {
    setStarted(true);
    setCurrentQuestion(0);
    setSelectedAnswer(null);
    setScore(0);
    setLevel("");
    setAnswers([]);
    setFinished(false);
    setSaving(false);
    setSaveMessage("");
    setSaveError("");
  };

  const handleNext = async () => {
    if (selectedAnswer === null) return;

    const submittedAnswers = [...answers, selectedAnswer];
    setAnswers(submittedAnswers);

    if (currentQuestion === questions.length - 1) {
      setSaving(true);
      setSaveError("");

      try {
        const response = await authFetch(
          "/api/test-results",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ answers: submittedAnswers }),
          }
        );

        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            data.detail || "حدث خطأ أثناء حفظ النتيجة."
          );
        }

        setScore(data.result.score);
        setLevel(data.result.level);
        setSaveMessage("تم حفظ نتيجتك بنجاح.");
      } catch (error) {
        setSaveError(error.message);
      } finally {
        setSaving(false);
        setFinished(true);
      }

      return;
    }

    setCurrentQuestion((prev) => prev + 1);
    setSelectedAnswer(null);
  };

  if (!started) {
    return (
      <div
        dir={ar ? "rtl" : "ltr"}
        style={{
          minHeight: "100vh",
          background: "var(--fp-canvas)",
          padding: "60px 8%",
          fontFamily: "Arial, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: "800px",
            width: "100%",
            boxSizing: "border-box",
            margin: "0 auto",
            background: "#fff",
            padding: "45px",
            borderRadius: "24px",
            boxShadow: "0 15px 40px rgba(0,0,0,0.08)",
            textAlign: "center",
          }}
        >
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
            <button type="button" onClick={() => setLanguage(ar ? "en" : "ar")} style={languageButtonStyle}>{ar ? "English" : "العربية"}</button>
          </div>
          <h1 style={{ color: "var(--fp-primary)", fontSize: "40px" }}>
            {ar ? "الاختبار التجريبي" : "Placement test"}
          </h1>

          <p
            style={{
              fontSize: "19px",
              lineHeight: "1.8",
              color: "#475569",
            }}
          >
            {ar ? "يساعدك هذا الاختبار التجريبي على الحصول على مؤشر أولي لمستواك في اللغة الإنجليزية." : "This short placement test gives you an initial estimate of your English level. Questions are in English."}
          </p>

          <button
            onClick={handleStart}
            style={{
              marginTop: "25px",
              padding: "15px 32px",
              border: "none",
              borderRadius: "12px",
              background: "var(--fp-primary)",
              color: "#fff",
              fontSize: "18px",
              fontWeight: "700",
              cursor: "pointer",
            }}
          >
            {ar ? "ابدأ الاختبار" : "Start test"}
          </button>
        </div>
      </div>
    );
  }

  if (finished) {
    return (
      <div
        dir={ar ? "rtl" : "ltr"}
        style={{
          minHeight: "100vh",
          background: "var(--fp-canvas)",
          padding: "60px 8%",
          fontFamily: "Arial, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: "800px",
            width: "100%",
            boxSizing: "border-box",
            margin: "0 auto",
            background: "#fff",
            padding: "45px",
            borderRadius: "24px",
            textAlign: "center",
            boxShadow: "0 15px 40px rgba(0,0,0,0.08)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
            <button type="button" onClick={() => setLanguage(ar ? "en" : "ar")} style={languageButtonStyle}>{ar ? "English" : "العربية"}</button>
          </div>
          <h1 style={{ color: "var(--fp-primary)" }}>
            {ar ? "انتهى الاختبار 🎉" : "Test complete 🎉"}
          </h1>

          <p style={{ fontSize: "22px", marginTop: "25px" }}>
            {ar ? `نتيجتك: ${score} من ${questions.length}` : `Your score: ${score} of ${questions.length}`}
          </p>

          <h2 style={{ marginTop: "20px" }}>
            {ar ? `المستوى الأولي المقترح: ${level || "—"}` : `Suggested starting level: ${level || "—"}`}
          </h2>

          {saving && (
            <p style={{ color: "var(--fp-muted)" }}>
              {ar ? "جارٍ حفظ النتيجة..." : "Saving your result..."}
            </p>
          )}

          {saveMessage && (
            <p style={{ color: "#16a34a", fontWeight: "700" }}>
              {ar ? saveMessage : "Your result was saved successfully."}
            </p>
          )}

          {saveError && (
            <p style={{ color: "#dc2626", fontWeight: "700" }}>
              {ar ? saveError : "There was a problem saving your result. Please try again."}
            </p>
          )}

          {saveMessage && (
            <button
              onClick={() => navigate("/student-dashboard", { replace: true })}
              style={{
                marginTop: "12px",
                padding: "14px 28px",
                border: "none",
                borderRadius: "12px",
                background: "var(--fp-primary)",
                color: "#fff",
                fontSize: "17px",
                fontWeight: "700",
                cursor: "pointer",
              }}
            >
              {ar ? "لوحة الطالب" : "Student dashboard"}
            </button>
          )}

          <button
            onClick={handleStart}
            style={{
              marginTop: "25px",
              padding: "14px 28px",
              border: "none",
              borderRadius: "12px",
              background: "var(--fp-primary)",
              color: "#fff",
              fontSize: "17px",
              cursor: "pointer",
            }}
          >
            {ar ? "إعادة الاختبار" : "Retake test"}
          </button>
        </div>
      </div>
    );
  }

  const question = questions[currentQuestion];

  return (
    <div
      dir={ar ? "rtl" : "ltr"}
      style={{
        minHeight: "100vh",
        background: "var(--fp-canvas)",
        padding: "50px 8%",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "850px",
          width: "100%",
          boxSizing: "border-box",
          margin: "0 auto",
          background: "#fff",
          padding: "40px",
          borderRadius: "24px",
          boxShadow: "0 15px 40px rgba(0,0,0,0.08)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
          <button type="button" onClick={() => setLanguage(ar ? "en" : "ar")} style={languageButtonStyle}>{ar ? "English" : "العربية"}</button>
        </div>
        <p
          style={{
            color: "var(--fp-muted)",
            marginBottom: "10px",
          }}
        >
          Question {currentQuestion + 1} of {questions.length}
        </p>

        <h2
          style={{
            fontSize: "28px",
            marginBottom: "30px",
          }}
        >
          {question.question}
        </h2>

        <div>
          {question.options.map((option, index) => (
            <button
              key={option}
              onClick={() => setSelectedAnswer(index)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "16px",
                marginBottom: "12px",
                borderRadius: "12px",
                border:
                  selectedAnswer === index
                    ? "2px solid var(--fp-primary)"
                    : "1px solid #d1d5db",
                background:
                  selectedAnswer === index
                    ? "#eef2ff"
                    : "#fff",
                cursor: "pointer",
                fontSize: "16px",
              }}
            >
              {option}
            </button>
          ))}
        </div>

        <button
          onClick={handleNext}
          disabled={selectedAnswer === null || saving}
          style={{
            marginTop: "20px",
            padding: "14px 30px",
            border: "none",
            borderRadius: "12px",
            background:
              selectedAnswer === null || saving
                ? "#cbd5e1"
                : "var(--fp-primary)",
            color: "#fff",
            fontSize: "17px",
            cursor:
              selectedAnswer === null || saving
                ? "not-allowed"
                : "pointer",
          }}
        >
          {saving
            ? "جارٍ الحفظ..."
            : currentQuestion === questions.length - 1
              ? (ar ? "إنهاء الاختبار" : "Finish test")
              : (ar ? "السؤال التالي" : "Next question")}
        </button>
      </div>
    </div>
  );
}

const languageButtonStyle = {
  border: "1px solid var(--fp-border)",
  borderRadius: "9px",
  padding: "9px 14px",
  background: "#fff",
  color: "var(--fp-muted)",
  cursor: "pointer",
};

export default TrialTest;
