import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { ClassState, ClassStatus, formatClassDate } from "./ClassComponents";
import "./Class.css";
import "./ClassStaff.css";

const copy = {
  ar: { title: "الحصص", subtitle: "أنشئ جدول الحصص وراجع القادمة والسابقة.", create: "إنشاء حصة", upcoming: "القادمة", past: "السابقة", cancelled: "الملغاة", edit: "تعديل", cancel: "إلغاء الحصة", cancelling: "جارٍ الإلغاء...", empty: "لا توجد حصص في هذا القسم.", loading: "جارٍ تحميل الحصص...", confirm: "هل تريد إلغاء هذه الحصة؟", join: "انضمام", start: "بدء اجتماع Zoom" },
  en: { title: "Classes", subtitle: "Schedule classes and review upcoming and past sessions.", create: "Create class", upcoming: "Upcoming", past: "Past", cancelled: "Cancelled", edit: "Edit", cancel: "Cancel class", cancelling: "Cancelling...", empty: "There are no classes in this section.", loading: "Loading classes...", confirm: "Cancel this class?", join: "Join", start: "Start Zoom meeting" },
};

function TeacherClasses() {
  const [language, setLanguage] = useState("ar");
  const [classes, setClasses] = useState([]);
  const [tab, setTab] = useState("upcoming");
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState("");
  const [startingId, setStartingId] = useState("");
  const [error, setError] = useState("");
  const text = copy[language];

  const loadClasses = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/teacher/classes");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to load classes");
      setClasses(payload.classes || []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadClasses(); }, [loadClasses]);

  const cancelClass = async (classId) => {
    if (!window.confirm(text.confirm)) return;
    setSavingId(classId);
    setError("");
    try {
      const response = await authFetch(`/api/teacher/classes/${classId}/cancel`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to cancel class");
      setClasses((current) => current.map((item) => item.id === classId ? payload.class : item));
    } catch (cancelError) {
      setError(cancelError.message);
    } finally {
      setSavingId("");
    }
  };

  const startZoomClass = async (classId) => {
    setStartingId(classId);
    setError("");
    try {
      const response = await authFetch(`/api/teacher/classes/${classId}/zoom-start`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to start Zoom meeting");
      window.location.assign(payload.startUrl);
    } catch (startError) {
      setError(startError.message);
    } finally {
      setStartingId("");
    }
  };

  const visibleClasses = classes.filter((item) => tab === "cancelled" ? item.status === "cancelled" : item.status !== "cancelled" && item.timeState === tab);

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="teacher" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / SCHEDULE</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><Link className="class-create-button" to="/teacher-classes/new">+ {text.create}</Link></header>
      <div className="class-tabs" role="tablist">{["upcoming", "past", "cancelled"].map((key) => <button type="button" role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}>{text[key]} <span>{classes.filter((item) => key === "cancelled" ? item.status === key : item.status !== "cancelled" && item.timeState === key).length}</span></button>)}</div>
      {loading ? <ClassState language={language} loading> {text.loading}</ClassState> : error && !classes.length ? <ClassState language={language} error={error} onRetry={loadClasses} /> : visibleClasses.length ? <div className="teacher-class-list">{visibleClasses.map((item) => <article className="teacher-class-row" key={item.id}><div className="teacher-class-main"><ClassStatus classItem={item} language={language} /><h2>{item.title}</h2><p>{formatClassDate(item, language)} · {item.startTime} - {item.endTime}</p><small>{item.courseId || item.level || "—"} · {(item.assignedStudentIds || []).length} {language === "ar" ? "طالب" : "students"}</small></div><div className="teacher-class-actions">{item.meetingProvider === "zoom" && item.status !== "cancelled" && <button type="button" disabled={startingId === item.id} onClick={() => startZoomClass(item.id)}>{startingId === item.id ? "…" : text.start}</button>}{item.meetingProvider !== "zoom" && item.teacherJoinUrl && item.status !== "cancelled" && <a href={item.teacherJoinUrl} target="_blank" rel="noreferrer">↗ {text.join}</a>}<Link to={`/teacher-classes/${item.id}/edit`}>{text.edit}</Link>{item.status !== "cancelled" && <button type="button" disabled={savingId === item.id} onClick={() => cancelClass(item.id)}>{savingId === item.id ? text.cancelling : text.cancel}</button>}</div></article>)}</div> : <ClassState language={language}>{text.empty}</ClassState>}
      {error && classes.length > 0 && <p role="alert" className="class-error">{error}</p>}
    </main>
  </div>;
}

export default TeacherClasses;
