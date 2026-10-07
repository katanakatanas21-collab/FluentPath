import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { HomeworkState, HomeworkStatus } from "./HomeworkComponents";
import "./Homework.css";
import "./HomeworkRefinements.css";

const copy = {
  ar: { title: "مراجعة التسليمات", subtitle: "راجع إجابات الطلاب وأضف الدرجة والملاحظات.", back: "العودة إلى الواجبات", noSubmissions: "لم يرسل الطلاب إجابات بعد.", loading: "جارٍ تحميل التسليمات...", grade: "الدرجة من 100", feedback: "ملاحظات المعلم", save: "حفظ التقييم", saving: "جارٍ الحفظ...", saved: "تم حفظ التقييم.", submitted: "تاريخ التسليم" },
  en: { title: "Review submissions", subtitle: "Read student responses and provide a grade and feedback.", back: "Back to homework", noSubmissions: "No student responses have been submitted yet.", loading: "Loading submissions...", grade: "Grade out of 100", feedback: "Teacher feedback", save: "Save grade", saving: "Saving...", saved: "Grade saved.", submitted: "Submitted" },
};

function TeacherHomeworkSubmissions() {
  const { homeworkId } = useParams();
  const [language, setLanguage] = useState("ar");
  const [homework, setHomework] = useState(null);
  const [submissions, setSubmissions] = useState([]);
  const [grades, setGrades] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const text = copy[language];

  const loadSubmissions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch(`/api/teacher/homework/${homeworkId}/submissions`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to load submissions");
      setHomework(payload.homework);
      setSubmissions(payload.submissions || []);
      setGrades(Object.fromEntries((payload.submissions || []).map((submission) => [submission.id, {
        grade: submission.grade ?? "",
        teacherFeedback: submission.teacherFeedback || "",
      }])));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [homeworkId]);

  useEffect(() => { loadSubmissions(); }, [loadSubmissions]);

  const saveGrade = async (event, submission) => {
    event.preventDefault();
    setSavingId(submission.id);
    setError("");
    setMessage("");
    try {
      const values = grades[submission.id] || {};
      const response = await authFetch(`/api/teacher/homework/${homeworkId}/submissions/${submission.id}/grade`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: values.grade === "" ? null : Number(values.grade), teacherFeedback: values.teacherFeedback || "" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to save grade");
      setSubmissions((current) => current.map((item) => item.id === submission.id ? { ...item, ...payload.submission } : item));
      setMessage(text.saved);
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSavingId("");
    }
  };

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="teacher" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / REVIEW</p><h1>{homework?.title || text.title}</h1><p>{text.subtitle}</p></div><Link className="homework-back-link" to="/teacher-homework">{text.back}</Link></header>
      {loading ? <HomeworkState language={language}>{text.loading}</HomeworkState> : error && !homework ? <HomeworkState language={language} error={error} onRetry={loadSubmissions} /> : <>
        <section className="submission-panel"><h2>{text.title} <span className="homework-count">{submissions.length}</span></h2>
          {submissions.length ? submissions.map((submission) => <article className="submission-panel" key={submission.id}><div className="submission-student"><strong>{submission.student?.fullName || submission.studentId}</strong><small>{submission.student?.email}</small></div><div className="teacher-submission-meta"><HomeworkStatus status={submission.status} language={language} /><span>{text.submitted}: {submission.submittedAt ? new Date(submission.submittedAt).toLocaleString(language === "ar" ? "ar" : "en") : "—"}</span></div><div className="submission-answer">{submission.answer}</div><form className="grading-form" onSubmit={(event) => saveGrade(event, submission)}><div><label htmlFor={`grade-${submission.id}`}>{text.grade}</label><input id={`grade-${submission.id}`} type="number" min="0" max="100" step="0.5" value={grades[submission.id]?.grade ?? ""} onChange={(event) => setGrades({ ...grades, [submission.id]: { ...grades[submission.id], grade: event.target.value } })} /></div><div><label htmlFor={`feedback-${submission.id}`}>{text.feedback}</label><textarea id={`feedback-${submission.id}`} rows="2" value={grades[submission.id]?.teacherFeedback || ""} onChange={(event) => setGrades({ ...grades, [submission.id]: { ...grades[submission.id], teacherFeedback: event.target.value } })} /></div><button type="submit" disabled={savingId === submission.id}>{savingId === submission.id ? text.saving : text.save}</button></form>{error && <p role="alert" className="homework-error">{error}</p>}{message && <p role="status" className="homework-success">{message}</p>}</article>) : <HomeworkState language={language}>{text.noSubmissions}</HomeworkState>}
        </section>
      </>}
    </main>
  </div>;
}

export default TeacherHomeworkSubmissions;
