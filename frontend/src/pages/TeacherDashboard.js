import { useCallback, useEffect, useState } from "react";
import StaffNavigation from "./StaffNavigation";
import { MvpNotice, StaffStat, StaffState } from "./StaffComponents";
import { authFetch } from "../auth";
import "./StaffDashboard.css";

const translations = {
  ar: { title: "لوحة المعلم", subtitle: "تابع طلابك ودروسك من مساحة عمل واحدة.", welcome: "مساحة المعلم", overview: "نظرة عملية على الطلاب والدورات والواجبات.", students: "سجل الطلاب", courses: "الدورات", homework: "الواجبات", classes: "الحصص القادمة", studentList: "قائمة الطلاب", courseList: "الدورات والدروس", classesTitle: "الحصص القادمة", name: "الطالب", level: "المستوى", score: "الاختبار", progress: "التقدم", noStudents: "لا يوجد طلاب مرتبطون بحصصك أو واجباتك بعد.", noClasses: "لا توجد حصص مسجلة.", noHomework: "لا توجد واجبات بعد.", createHomework: "إنشاء واجب", titleLabel: "عنوان الواجب", description: "وصف الواجب", course: "الدورة", create: "حفظ الواجب", saving: "جارٍ الحفظ...", saved: "تم حفظ الواجب", assignmentNote: "يعرض هذا السجل الطلاب المرتبطين بحصصك أو بواجباتك فقط." },
  en: { title: "Teacher Dashboard", subtitle: "Keep track of your students and lessons from one workspace.", welcome: "Teacher workspace", overview: "A practical view of students, courses, and homework.", students: "Student roster", courses: "Courses", homework: "Homework", classes: "Upcoming classes", studentList: "Student list", courseList: "Courses and lessons", classesTitle: "Upcoming classes", name: "Student", level: "Level", score: "Test", progress: "Progress", noStudents: "No students are linked to your classes or homework yet.", noClasses: "No classes scheduled.", noHomework: "No homework yet.", createHomework: "Create homework", titleLabel: "Homework title", description: "Homework description", course: "Course", create: "Save homework", saving: "Saving...", saved: "Homework saved", assignmentNote: "This roster only includes students linked to your classes or homework." },
};

function TeacherDashboard() {
  const [language, setLanguage] = useState("ar");
  const [data, setData] = useState({ dashboard: null, students: [], courses: [], homework: [], classes: [] });
  const [form, setForm] = useState({ title: "", description: "", courseId: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const text = translations[language];

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const paths = ["/api/teacher/dashboard", "/api/teacher/students", "/api/teacher/courses", "/api/teacher/homework", "/api/teacher/classes"];
      const responses = await Promise.all(paths.map((path) => authFetch(path)));
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failedIndex = responses.findIndex((response) => !response.ok);
      if (failedIndex >= 0) throw new Error(payloads[failedIndex].detail || "Unable to load teacher data");
      setData({ dashboard: payloads[0], students: payloads[1].students || [], courses: payloads[2].courses || [], homework: payloads[3].homework || [], classes: payloads[4].classes || [] });
      setForm((current) => ({ ...current, courseId: current.courseId || payloads[2].courses?.[0]?.id || "" }));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const createHomework = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const response = await authFetch("/api/teacher/homework", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to save homework");
      setMessage(text.saved);
      setForm((current) => ({ ...current, title: "", description: "" }));
      await loadData();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <StaffState message={language === "ar" ? "جارٍ تحميل لوحة المعلم..." : "Loading teacher dashboard..."} />;
  if (error && !data.dashboard) return <StaffState error={error} message={error} onRetry={loadData} />;

  const studentRows = data.students.map((student) => {
    const progress = student.courseProgress.find((item) => item.progress.percentage > 0) || student.courseProgress[0];
    return <tr key={student.id}><td>{student.fullName}</td><td><span className="level-pill">{student.level || "—"}</span></td><td>{student.testScore == null ? "—" : `${student.testScore}/${student.totalQuestions}`}</td><td>{progress ? <div className="mini-progress"><span><i style={{ width: `${progress.progress.percentage}%` }} /></span><small>{progress.progress.percentage}%</small></div> : "—"}</td></tr>;
  });
  const teacher = data.dashboard.currentUser;

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="teacher" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / TEACHER</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><div className="staff-account"><span>{teacher.fullName.charAt(0).toUpperCase()}</span><div><strong>{teacher.fullName}</strong><small>{teacher.email}</small></div></div></header>
      <section className="staff-hero"><div><span className="staff-eyebrow" style={{ color: "var(--fp-accent-border)" }}>{text.welcome}</span><h2>{text.overview}</h2><p>{language === "ar" ? "البيانات المعروضة محفوظة من النظام." : "The data shown here is persisted by the platform."}</p></div><div className="staff-hero-badge">T</div></section>
      <section className="staff-stats"><StaffStat icon="♙" label={text.students} value={data.dashboard.assignedStudents} detail={text.studentList} /><StaffStat icon="◈" label={text.courses} value={data.dashboard.courses} detail={text.courseList} /><StaffStat icon="✓" label={text.homework} value={data.dashboard.homework} detail={text.homework} /><StaffStat icon="◷" label={text.classes} value={data.dashboard.upcomingClasses.length} detail={text.classesTitle} /></section>
      <div className="staff-grid"><section className="staff-panel" id="students"><div className="staff-panel-heading"><div><span>01 / STUDENTS</span><h2>{text.studentList}</h2></div><small>{data.students.length}</small></div><MvpNotice>{text.assignmentNote}</MvpNotice><div className="staff-table-wrap"><table className="staff-table"><thead><tr><th>{text.name}</th><th>{text.level}</th><th>{text.score}</th><th>{text.progress}</th></tr></thead><tbody>{studentRows.length ? studentRows : <tr><td colSpan="4" className="staff-empty">{text.noStudents}</td></tr>}</tbody></table></div></section><section className="staff-panel" id="classes"><div className="staff-panel-heading"><div><span>02 / CLASSES</span><h2>{text.classesTitle}</h2></div><small>{data.dashboard.upcomingClasses.length}</small></div><div className="class-list">{data.dashboard.upcomingClasses.length ? data.dashboard.upcomingClasses.map((item) => <div className="class-item" key={item.id}><strong>{item.title}</strong><small>{new Date(item.startsAt).toLocaleString(language === "ar" ? "ar" : "en-US")} · {item.durationMinutes} min</small></div>) : <p className="staff-empty">{text.noClasses}</p>}</div></section></div>
      <div className="staff-grid"><section className="staff-panel" id="courses"><div className="staff-panel-heading"><div><span>03 / CONTENT</span><h2>{text.courseList}</h2></div><small>{data.courses.length}</small></div><div className="course-mini-list">{data.courses.map((course) => <div className="course-mini" key={course.id}><strong>{language === "ar" ? course.titleAr : course.title}</strong><small>{course.level} · {course.lessons.length} {language === "ar" ? "دروس" : "lessons"}</small></div>)}</div></section><section className="staff-panel" id="homework"><div className="staff-panel-heading"><div><span>04 / HOMEWORK</span><h2>{text.createHomework}</h2></div></div><form className="staff-form" onSubmit={createHomework}><label htmlFor="homework-title">{text.titleLabel}</label><input id="homework-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /><label htmlFor="homework-description">{text.description}</label><textarea id="homework-description" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} required /><label htmlFor="homework-course">{text.course}</label><select id="homework-course" value={form.courseId} onChange={(event) => setForm({ ...form, courseId: event.target.value })} required>{data.courses.map((course) => <option value={course.id} key={course.id}>{course.title}</option>)}</select><button type="submit" disabled={saving}>{saving ? text.saving : text.create}</button></form>{error && <p role="alert" className="staff-empty">{error}</p>}{message && <p role="status" className="staff-empty">{message}</p>}<div className="homework-list">{data.homework.map((item) => <div className="homework-item" key={item.id}><strong>{item.title}</strong><small>{item.description}</small></div>)}{!data.homework.length && <p className="staff-empty">{text.noHomework}</p>}</div></section></div>
    </main>
  </div>;
}

export default TeacherDashboard;
