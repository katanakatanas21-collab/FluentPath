import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { ClassState } from "./ClassComponents";
import "./Class.css";
import "./ClassStaff.css";

const copy = {
  ar: { title: "إنشاء حصة", editTitle: "تعديل الحصة", name: "عنوان الحصة", description: "الوصف", course: "الدورة", noCourse: "بدون دورة محددة", level: "المستوى", noLevel: "بدون مستوى محدد", students: "طلاب محددون (اختياري)", target: "عند عدم اختيار طلاب، تُسند الحصة للطلاب المؤهلين للدورة أو المستوى.", date: "التاريخ", start: "وقت البدء", end: "وقت الانتهاء", provider: "مزود الاجتماع", none: "رابط يدوي / بدون تكامل", zoom: "إنشاء اجتماع Zoom تلقائيًا", meeting: "رابط الاجتماع", teacherUrl: "رابط انضمام المعلم (اختياري)", studentUrl: "رابط انضمام الطالب (اختياري)", save: "حفظ الحصة", saving: "جارٍ الحفظ...", saved: "تم حفظ الحصة.", back: "العودة إلى الحصص", loading: "جارٍ تحميل النموذج...", noStudents: "لا يوجد طلاب.", zoomConfigured: "Zoom متصل. سيتم إنشاء الاجتماع تلقائيًا.", zoomMissing: "Zoom غير مُعد على الخادم. اطلب من المسؤول إعداد تكامل Zoom قبل حفظ الحصة.", zoomError: "تعذر الاتصال بـ Zoom. لم يتم حفظ الحصة؛ حاول مرة أخرى." },
  en: { title: "Create class", editTitle: "Edit class", name: "Class title", description: "Description", course: "Course", noCourse: "No specific course", level: "Level", noLevel: "No level selected", students: "Specific students (optional)", target: "Without selected students, the class is assigned to eligible students for its course or level.", date: "Date", start: "Start time", end: "End time", provider: "Meeting provider", none: "Manual link / no integration", zoom: "Create Zoom meeting automatically", meeting: "Meeting URL", teacherUrl: "Teacher join URL (optional)", studentUrl: "Student join URL (optional)", save: "Save class", saving: "Saving...", saved: "Class saved.", back: "Back to classes", loading: "Loading form...", noStudents: "No students available.", zoomConfigured: "Zoom is connected. A meeting will be created automatically.", zoomMissing: "Zoom is not configured on the server. Ask an administrator to configure the Zoom integration before saving this class.", zoomError: "Could not connect to Zoom. The class was not saved; try again." },
};

const levels = ["A0", "A1", "A2", "B1", "B2", "C1", "C1+"];

function TeacherClassForm() {
  const { classId } = useParams();
  const navigate = useNavigate();
  const [language, setLanguage] = useState("ar");
  const [courses, setCourses] = useState([]);
  const [students, setStudents] = useState([]);
  const [form, setForm] = useState({ title: "", description: "", courseId: "", level: "", studentIds: [], date: "", startTime: "16:00", endTime: "16:45", meetingProvider: "none", meetingUrl: "", teacherJoinUrl: "", studentJoinUrl: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [zoomConfigured, setZoomConfigured] = useState(false);
  const [legacyManualZoom, setLegacyManualZoom] = useState(false);
  const text = copy[language];

  const loadForm = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const paths = ["/api/teacher/courses", "/api/teacher/students", "/api/teacher/classes", "/api/teacher/meeting-options"];
      const responses = await Promise.all(paths.map((path) => authFetch(path)));
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failed = responses.findIndex((response) => !response.ok);
      if (failed >= 0) throw new Error(payloads[failed].detail || "Unable to load class form");
      setCourses(payloads[0].courses || []);
      setStudents(payloads[1].students || []);
      setZoomConfigured(Boolean(payloads[3].zoomConfigured));
      if (classId) {
        const current = (payloads[2].classes || []).find((item) => item.id === classId);
        if (!current) throw new Error("Class not found or access denied");
        const isLegacyManualZoom = current.meetingProvider === "zoom" && !current.zoomMeetingId && Boolean(current.meetingUrl || current.teacherJoinUrl || current.studentJoinUrl);
        setLegacyManualZoom(isLegacyManualZoom);
        setForm({
          title: current.title || "", description: current.description || "", courseId: current.courseId || "", level: current.level || "", studentIds: current.assignedStudentIds || [],
          date: current.date || "", startTime: current.startTime || "16:00", endTime: current.endTime || "16:45", meetingProvider: current.meetingProvider || "none", meetingUrl: isLegacyManualZoom || current.meetingProvider !== "zoom" ? current.meetingUrl || "" : "", teacherJoinUrl: isLegacyManualZoom || current.meetingProvider !== "zoom" ? current.teacherJoinUrl || "" : "", studentJoinUrl: isLegacyManualZoom || current.meetingProvider !== "zoom" ? current.studentJoinUrl || "" : "",
        });
      }
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [classId]);

  useEffect(() => { loadForm(); }, [loadForm]);

  const toggleStudent = (studentId) => setForm((current) => ({ ...current, studentIds: current.studentIds.includes(studentId) ? current.studentIds.filter((id) => id !== studentId) : [...current.studentIds, studentId] }));

  const saveClass = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const startsAt = new Date(`${form.date}T${form.startTime}`).toISOString();
      const response = await authFetch(classId ? `/api/teacher/classes/${classId}` : "/api/teacher/classes", {
        method: classId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, courseId: form.courseId || null, level: form.level || null, startsAt, meetingUrl: form.meetingUrl || null, teacherJoinUrl: form.teacherJoinUrl || null, studentJoinUrl: form.studentJoinUrl || null }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail === "Zoom is temporarily unavailable" ? text.zoomError : payload.detail || "Unable to save class");
      setMessage(text.saved);
      navigate("/teacher-classes", { replace: true });
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  };

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="teacher" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / SCHEDULE</p><h1>{classId ? text.editTitle : text.title}</h1></div><Link className="homework-back-link" to="/teacher-classes">{text.back}</Link></header>
      {loading ? <ClassState language={language} loading>{text.loading}</ClassState> : error && !courses.length ? <ClassState language={language} error={error} onRetry={loadForm} /> : <>
        <form className="class-form" onSubmit={saveClass}>
          <label htmlFor="class-title">{text.name}</label><input id="class-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required maxLength="160" />
          <label htmlFor="class-description">{text.description}</label><textarea id="class-description" rows="3" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} maxLength="3000" />
          <label htmlFor="class-course">{text.course}</label><select id="class-course" value={form.courseId} onChange={(event) => setForm({ ...form, courseId: event.target.value })}><option value="">{text.noCourse}</option>{courses.map((course) => <option key={course.id} value={course.id}>{language === "ar" ? course.titleAr : course.title} · {course.level}</option>)}</select>
          <label htmlFor="class-level">{text.level}</label><select id="class-level" value={form.level} onChange={(event) => setForm({ ...form, level: event.target.value })}><option value="">{text.noLevel}</option>{levels.map((level) => <option key={level} value={level}>{level}</option>)}</select>
          <div className="class-form-time"><div><label htmlFor="class-date">{text.date}</label><input id="class-date" type="date" value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })} required /></div><div><label htmlFor="class-start">{text.start}</label><input id="class-start" type="time" value={form.startTime} onChange={(event) => setForm({ ...form, startTime: event.target.value })} required /></div><div><label htmlFor="class-end">{text.end}</label><input id="class-end" type="time" value={form.endTime} onChange={(event) => setForm({ ...form, endTime: event.target.value })} required /></div></div>
          <label htmlFor="class-provider">{text.provider}</label><select id="class-provider" value={form.meetingProvider} onChange={(event) => { setLegacyManualZoom(false); setForm({ ...form, meetingProvider: event.target.value, ...(event.target.value === "zoom" ? { meetingUrl: "", teacherJoinUrl: "", studentJoinUrl: "" } : {}) }); }}><option value="none">{text.none}</option><option value="zoom">{text.zoom}</option></select>
          {form.meetingProvider === "zoom" && !legacyManualZoom ? <p role="status" className="class-meeting-status">{zoomConfigured ? text.zoomConfigured : text.zoomMissing}</p> : <>
            <label htmlFor="class-meeting-url">{text.meeting}</label><input id="class-meeting-url" type="url" placeholder="https://..." value={form.meetingUrl} onChange={(event) => setForm({ ...form, meetingUrl: event.target.value })} />
            <label htmlFor="class-teacher-url">{text.teacherUrl}</label><input id="class-teacher-url" type="url" placeholder="https://..." value={form.teacherJoinUrl} onChange={(event) => setForm({ ...form, teacherJoinUrl: event.target.value })} />
            <label htmlFor="class-student-url">{text.studentUrl}</label><input id="class-student-url" type="url" placeholder="https://..." value={form.studentJoinUrl} onChange={(event) => setForm({ ...form, studentJoinUrl: event.target.value })} />
          </>}
          <label>{text.students}</label><div className="class-student-picker">{students.length ? students.map((student) => <label className="class-student-option" key={student.id}><input type="checkbox" checked={form.studentIds.includes(student.id)} onChange={() => toggleStudent(student.id)} /><span>{student.fullName}<small>{student.level || "—"}</small></span></label>) : <small>{text.noStudents}</small>}</div>
          <small>{text.target}</small><button type="submit" disabled={saving}>{saving ? text.saving : text.save}</button>{error && <p role="alert" className="class-error">{error}</p>}{message && <p role="status">{message}</p>}
        </form>
      </>}
    </main>
  </div>;
}

export default TeacherClassForm;
