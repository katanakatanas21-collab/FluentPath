import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { HomeworkState, HomeworkStatus } from "./HomeworkComponents";
import "./Homework.css";

const copy = {
  ar: { title: "إدارة الواجبات", subtitle: "أنشئ واجبات، حدّد الطلاب، وراجع التسليمات والتقييمات.", create: "إنشاء واجب", list: "الواجبات المنشورة", titleLabel: "عنوان الواجب", description: "التعليمات", course: "الدورة", noCourse: "بدون دورة محددة", level: "المستوى الأدنى (اختياري)", noLevel: "بدون حد للمستوى", students: "طلاب محددون (اختياري)", targetHint: "إذا لم تحدد طلابًا، يُسند الواجب إلى الطلاب المؤهلين للدورة أو المستوى.", dueDate: "موعد التسليم", save: "نشر الواجب", saving: "جارٍ النشر...", saved: "تم نشر الواجب.", empty: "لم تنشئ واجبات بعد.", loading: "جارٍ تحميل البيانات...", submissions: "تسليمات", assigned: "مسند", allStudents: "لا يوجد طلاب متاحون." },
  en: { title: "Homework management", subtitle: "Create work, target students, and review submissions and grades.", create: "Create homework", list: "Published homework", titleLabel: "Homework title", description: "Instructions", course: "Course", noCourse: "No specific course", level: "Minimum CEFR level (optional)", noLevel: "No level minimum", students: "Specific students (optional)", targetHint: "With no selected students, eligible students are assigned by course or level.", dueDate: "Due date", save: "Publish homework", saving: "Publishing...", saved: "Homework published.", empty: "You have not created homework yet.", loading: "Loading workspace...", submissions: "submissions", assigned: "Assigned", allStudents: "No students available." },
};

const levels = ["A0", "A1", "A2", "B1", "B2", "C1", "C1+"];

function TeacherHomework() {
  const [language, setLanguage] = useState("ar");
  const [courses, setCourses] = useState([]);
  const [students, setStudents] = useState([]);
  const [homework, setHomework] = useState([]);
  const [form, setForm] = useState({ title: "", description: "", courseId: "", level: "", dueDate: "", studentIds: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const text = copy[language];

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const paths = ["/api/teacher/homework", "/api/teacher/courses", "/api/teacher/students"];
      const responses = await Promise.all(paths.map((path) => authFetch(path)));
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failed = responses.findIndex((response) => !response.ok);
      if (failed >= 0) throw new Error(payloads[failed].detail || "Unable to load homework workspace");
      setHomework(payloads[0].homework || []);
      setCourses(payloads[1].courses || []);
      setStudents(payloads[2].students || []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const toggleStudent = (studentId) => setForm((current) => ({
    ...current,
    studentIds: current.studentIds.includes(studentId)
      ? current.studentIds.filter((id) => id !== studentId)
      : [...current.studentIds, studentId],
  }));

  const createHomework = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await authFetch("/api/teacher/homework", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          courseId: form.courseId || null,
          level: form.level || null,
          dueDate: form.dueDate ? new Date(form.dueDate).toISOString() : null,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to publish homework");
      setMessage(text.saved);
      setForm({ title: "", description: "", courseId: "", level: "", dueDate: "", studentIds: [] });
      await loadData();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  };

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="teacher" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / TEACHING</p><h1>{text.title}</h1><p>{text.subtitle}</p></div></header>
      {loading ? <HomeworkState language={language}>{text.loading}</HomeworkState> : error && !courses.length ? <HomeworkState language={language} error={error} onRetry={loadData} /> : <div className="teacher-homework-grid">
        <section className="teacher-homework-panel"><h2>{text.create}</h2><form className="teacher-homework-form" onSubmit={createHomework}>
          <label htmlFor="teacher-homework-title">{text.titleLabel}</label><input id="teacher-homework-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required maxLength="160" />
          <label htmlFor="teacher-homework-description">{text.description}</label><textarea id="teacher-homework-description" rows="4" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} required maxLength="5000" />
          <label htmlFor="teacher-homework-course">{text.course}</label><select id="teacher-homework-course" value={form.courseId} onChange={(event) => setForm({ ...form, courseId: event.target.value })}><option value="">{text.noCourse}</option>{courses.map((course) => <option key={course.id} value={course.id}>{language === "ar" ? course.titleAr : course.title} · {course.level}</option>)}</select>
          <label htmlFor="teacher-homework-level">{text.level}</label><select id="teacher-homework-level" value={form.level} onChange={(event) => setForm({ ...form, level: event.target.value })}><option value="">{text.noLevel}</option>{levels.map((level) => <option key={level} value={level}>{level}</option>)}</select>
          <label htmlFor="teacher-homework-due">{text.dueDate}</label><input id="teacher-homework-due" type="datetime-local" value={form.dueDate} onChange={(event) => setForm({ ...form, dueDate: event.target.value })} />
          <label>{text.students}</label><div className="teacher-student-picker">{students.length ? students.map((student) => <label className="teacher-student-option" key={student.id}><input type="checkbox" checked={form.studentIds.includes(student.id)} onChange={() => toggleStudent(student.id)} /><span>{student.fullName}<small>{student.level || "—"}</small></span></label>) : <small>{text.allStudents}</small>}</div>
          <small>{text.targetHint}</small><button type="submit" disabled={saving}>{saving ? text.saving : text.save}</button>
          {error && <p role="alert" className="homework-error">{error}</p>}{message && <p role="status" className="homework-success">{message}</p>}
        </form></section>
        <section className="teacher-homework-panel"><h2>{text.list} <span className="homework-count">{homework.length}</span></h2>{homework.length ? <div className="teacher-homework-list">{homework.map((item) => <Link className="teacher-homework-row" to={`/teacher-homework/${item.id}/submissions`} key={item.id}><div><strong>{item.title}</strong><small>{item.courseId ? courses.find((course) => course.id === item.courseId)?.title || item.courseId : item.level || text.assigned}</small></div><span><HomeworkStatus status={item.status} language={language} />{item.submissionCount || 0} {text.submissions}</span></Link>)}</div> : <HomeworkState language={language}>{text.empty}</HomeworkState>}</section>
      </div>}
    </main>
  </div>;
}

export default TeacherHomework;

