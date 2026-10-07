import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { authFetch } from "../auth";
import { HomeworkNavigation, HomeworkState, HomeworkStatus } from "./HomeworkComponents";
import "./Homework.css";
import "./HomeworkRefinements.css";

const copy = {
  ar: { title: "تفاصيل الواجب", instructions: "التعليمات", course: "الدورة والمستوى", due: "موعد التسليم", answer: "إجابتك", submit: "إرسال الواجب", update: "تحديث التسليم", saving: "جارٍ الإرسال...", submitted: "تم حفظ إجابتك.", status: "حالة التسليم", grade: "الدرجة", feedback: "ملاحظات المعلم", locked: "تم تقييم هذا الواجب ولا يمكن تعديل الإجابة.", loading: "جارٍ تحميل الواجب...", back: "كل الواجبات" },
  en: { title: "Homework details", instructions: "Instructions", course: "Course and level", due: "Due date", answer: "Your response", submit: "Submit homework", update: "Update submission", saving: "Submitting...", submitted: "Your response has been saved.", status: "Submission status", grade: "Grade", feedback: "Teacher feedback", locked: "This homework has been graded and can no longer be edited.", loading: "Loading homework...", back: "All homework" },
};

function StudentHomeworkDetails() {
  const { homeworkId } = useParams();
  const [language, setLanguage] = useState("ar");
  const [homework, setHomework] = useState(null);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const text = copy[language];

  const loadHomework = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch(`/api/student/homework/${homeworkId}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Homework could not be loaded");
      setHomework(payload.homework);
      setAnswer(payload.homework.submission?.answer || "");
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [homeworkId]);

  useEffect(() => { loadHomework(); }, [loadHomework]);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await authFetch(`/api/student/homework/${homeworkId}/submissions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to submit homework");
      setMessage(text.submitted);
      await loadHomework();
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSaving(false);
    }
  };

  const courseName = language === "ar" ? homework?.course?.titleAr || homework?.course?.title : homework?.course?.title;
  const dueDate = homework?.dueDate ? new Date(homework.dueDate).toLocaleString(language === "ar" ? "ar" : "en") : "—";
  const graded = homework?.submission?.status === "graded";

  return <div className="homework-layout" dir={language === "ar" ? "rtl" : "ltr"}>
    <HomeworkNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="homework-main">
      <header className="homework-page-header"><div><p className="homework-eyebrow">FLUENT PATH / PRACTICE</p><h1>{homework?.title || text.title}</h1></div><Link className="homework-back-link" to="/homework">← {text.back}</Link></header>
      {loading ? <HomeworkState language={language}>{text.loading}</HomeworkState> : error && !homework ? <HomeworkState language={language} error={error} onRetry={loadHomework} /> : homework && <>
        <section className="homework-detail-panel"><div className="homework-detail-heading"><div><span className="homework-eyebrow">{text.instructions}</span><h2>{homework.title}</h2></div><HomeworkStatus status={homework.submission?.status || homework.status} language={language} /></div><p className="homework-instructions">{homework.description}</p><div className="homework-detail-meta"><div><small>{text.course}</small><strong>{courseName || homework.level || "—"}</strong></div><div><small>{text.due}</small><strong>{dueDate}</strong></div></div></section>
        {homework.submission && <section className="homework-feedback-panel"><div className="homework-detail-heading"><h2>{text.status}</h2><HomeworkStatus status={homework.submission.status} language={language} /></div>{homework.submission.status === "graded" && <><p><strong>{text.grade}: </strong>{homework.submission.grade == null ? "—" : `${homework.submission.grade}/100`}</p><p><strong>{text.feedback}: </strong>{homework.submission.teacherFeedback || "—"}</p></>}</section>}
        {graded ? <p className="homework-notice">{text.locked}</p> : <form className="homework-form" onSubmit={submit}><label htmlFor="homework-answer">{text.answer}</label><textarea id="homework-answer" value={answer} onChange={(event) => setAnswer(event.target.value)} required rows="8" /><button type="submit" disabled={saving}>{saving ? text.saving : homework.submission ? text.update : text.submit}</button>{error && <p role="alert" className="homework-error">{error}</p>}{message && <p role="status" className="homework-success">{message}</p>}</form>}
      </>}
    </main>
  </div>;
}

export default StudentHomeworkDetails;
