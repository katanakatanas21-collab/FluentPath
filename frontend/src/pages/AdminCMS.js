import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { StaffState } from "./StaffComponents";
import "./AdminCMS.css";

const levels = ["A0 → A1", "A1 → A2", "A2 → B1", "B1 → B2", "B2 → C1", "C1+"];
const contentFields = ["introduction", "explanation", "examples", "vocabulary", "grammar_notes", "practice_instructions"];
const isPublished = (lesson) => lesson.published !== false;
const strings = {
  en: { heading: "Content Studio", subtitle: "Shape each learning path with clear, structured lessons.", courses: "Course library", create: "Create course", edit: "Edit course", lessons: "Lessons", addLesson: "Add lesson", courseTitle: "Course title", titleAr: "Arabic title", description: "Description", descriptionAr: "Arabic description", level: "CEFR level", order: "Course order", save: "Save course", saving: "Saving…", active: "Active", inactive: "Inactive", activate: "Activate", deactivate: "Deactivate", view: "Manage lessons", back: "Content studio", draft: "Draft", published: "Published", publish: "Publish", unpublish: "Unpublish", archive: "Archive", restore: "Restore", confirmArchive: "Archive this lesson? Student progress will be preserved.", newLesson: "New lesson", editLesson: "Edit lesson", lessonTitle: "Lesson title", lessonTitleAr: "Arabic lesson title", lessonDescription: "Short description", lessonDescriptionAr: "Arabic description", estimated: "Estimated minutes", introduction: "Introduction", explanation: "Explanation", examples: "Examples", vocabulary: "Vocabulary", grammar_notes: "Grammar notes", practice_instructions: "Practice instructions", saveLesson: "Save lesson", noCourses: "No courses yet. Create the first learning path.", noLessons: "No lessons in this course yet.", retry: "Try again", orderSaved: "Lesson order updated", all: "All", status: "Status", count: "lessons", error: "Something went wrong." },
  ar: { heading: "استوديو المحتوى", subtitle: "صمّم مسارات التعلم بدروس واضحة ومنظمة.", courses: "مكتبة الدورات", create: "إنشاء دورة", edit: "تعديل الدورة", lessons: "الدروس", addLesson: "إضافة درس", courseTitle: "عنوان الدورة", titleAr: "العنوان بالعربية", description: "الوصف", descriptionAr: "الوصف بالعربية", level: "مستوى CEFR", order: "ترتيب الدورة", save: "حفظ الدورة", saving: "جارٍ الحفظ…", active: "مفعّلة", inactive: "غير مفعّلة", activate: "تفعيل", deactivate: "إيقاف", view: "إدارة الدروس", back: "استوديو المحتوى", draft: "مسودة", published: "منشور", publish: "نشر", unpublish: "إلغاء النشر", archive: "أرشفة", restore: "استعادة", confirmArchive: "أرشفة هذا الدرس؟ سيبقى تقدم الطلاب محفوظًا.", newLesson: "درس جديد", editLesson: "تعديل الدرس", lessonTitle: "عنوان الدرس", lessonTitleAr: "عنوان الدرس بالعربية", lessonDescription: "وصف قصير", lessonDescriptionAr: "الوصف بالعربية", estimated: "الوقت التقديري بالدقائق", introduction: "المقدمة", explanation: "الشرح", examples: "أمثلة", vocabulary: "المفردات", grammar_notes: "ملاحظات القواعد", practice_instructions: "تعليمات التدريب", saveLesson: "حفظ الدرس", noCourses: "لا توجد دورات بعد. أنشئ أول مسار تعليمي.", noLessons: "لا توجد دروس في هذه الدورة بعد.", retry: "إعادة المحاولة", orderSaved: "تم تحديث ترتيب الدروس", all: "الكل", status: "الحالة", count: "دروس", error: "حدث خطأ غير متوقع." },
};

const emptyCourse = { title: "", titleAr: "", description: "", descriptionAr: "", level: levels[0], order: "" };
const emptyLesson = { title: "", titleAr: "", description: "", descriptionAr: "", estimated_minutes: 15, content: Object.fromEntries(contentFields.map((key) => [key, ""])) };

async function jsonRequest(path, options = {}) {
  const response = await authFetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

export default function AdminCMS({ mode = "list" }) {
  const { courseId, lessonId } = useParams();
  const navigate = useNavigate();
  const [language, setLanguage] = useState("ar");
  const [courses, setCourses] = useState([]);
  const [course, setCourse] = useState(null);
  const [courseForm, setCourseForm] = useState(emptyCourse);
  const [lessonForm, setLessonForm] = useState(emptyLesson);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const text = strings[language];
  const isNewCourse = mode === "course-form" && !courseId;
  const visibleLessons = useMemo(() => (course?.lessons || []).filter((item) => !item.archived).sort((a, b) => (a.order || a.number || 0) - (b.order || b.number || 0)), [course]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      if (mode === "list") {
        const data = await jsonRequest("/api/admin/courses");
        setCourses(data.courses || []);
      } else if (courseId) {
        const data = await jsonRequest(`/api/admin/courses/${courseId}`);
        setCourse(data.course);
        setCourseForm({ ...emptyCourse, ...data.course, order: data.course.order ?? "" });
        if (mode === "lesson-form" && lessonId) {
          const lesson = data.course.lessons?.find((item) => item.id === lessonId);
          if (!lesson) throw new Error("Lesson not found");
          setLessonForm({ ...emptyLesson, ...lesson, content: { ...emptyLesson.content, ...(typeof lesson.content === "object" && lesson.content ? lesson.content : { explanation: lesson.content || "" }) } });
        }
      }
    } catch (loadError) { setError(loadError.message || text.error); }
    finally { setLoading(false); }
  }, [courseId, lessonId, mode, text.error]);

  useEffect(() => { load(); }, [load]);

  const mutate = async (path, method, body) => {
    setSaving(true); setError("");
    try {
      const payload = await jsonRequest(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      return payload;
    } catch (mutationError) { setError(mutationError.message || text.error); return null; }
    finally { setSaving(false); }
  };

  const saveCourse = async (event) => {
    event.preventDefault();
    const payload = { ...courseForm, order: courseForm.order === "" ? null : Number(courseForm.order) };
    const result = await mutate(isNewCourse ? "/api/admin/courses" : `/api/admin/courses/${courseId}`, isNewCourse ? "POST" : "PUT", payload);
    if (result) navigate(`/admin-content/courses/${result.course.id}`);
  };

  const saveLesson = async (event) => {
    event.preventDefault();
    const path = `/api/admin/courses/${courseId}/lessons${lessonId ? `/${lessonId}` : ""}`;
    const result = await mutate(path, lessonId ? "PUT" : "POST", { ...lessonForm, estimated_minutes: Number(lessonForm.estimated_minutes) });
    if (result) navigate(`/admin-content/courses/${courseId}`);
  };

  const setCourseStatus = async () => {
    const result = await mutate(`/api/admin/courses/${course.id}/status`, "PATCH", { active: !course.active });
    if (result) { setCourse((value) => ({ ...value, active: result.active })); await load(); }
  };

  const setLessonStatus = async (lesson, status) => {
    const result = await mutate(`/api/admin/courses/${courseId}/lessons/${lesson.id}/status`, "PATCH", status);
    if (result) await load();
  };

  const moveLesson = async (lesson, offset) => {
    const index = visibleLessons.findIndex((item) => item.id === lesson.id);
    const target = index + offset;
    if (target < 0 || target >= visibleLessons.length) return;
    const reordered = [...visibleLessons];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    const result = await mutate(`/api/admin/courses/${courseId}/lessons/reorder`, "POST", { lesson_ids: reordered.map((item) => item.id) });
    if (result) await load();
  };

  if (loading) return <StaffState message={language === "ar" ? "جارٍ تحميل استوديو المحتوى…" : "Loading content studio…"} />;
  if (error && !course && mode !== "list" && !isNewCourse) return <StaffState error={error} message={error} onRetry={load} />;

  const header = <header className="cms-heading"><div className="cms-arch-mark"><span>F</span></div><div><p>FLUENT PATH / CONTENT STUDIO</p><h1>{text.heading}</h1><span>{text.subtitle}</span></div><button type="button" onClick={() => setLanguage(language === "ar" ? "en" : "ar")}>{language === "ar" ? "English" : "العربية"}</button></header>;
  const courseFields = [
    ["title", text.courseTitle, "text"], ["titleAr", text.titleAr, "text"],
    ["description", text.description, "textarea"], ["descriptionAr", text.descriptionAr, "textarea"],
  ];

  return <div className="staff-shell cms-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="administrator" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main cms-main">
      {header}
      {error && <div className="cms-error" role="alert">{error}</div>}
      {mode === "list" && <>
        <section className="cms-toolbar"><div><span>01 / CEFR PATHS</span><h2>{text.courses}</h2></div><Link className="cms-primary" to="/admin-content/courses/new">＋ {text.create}</Link></section>
        <div className="cms-course-grid">{courses.length ? courses.map((item, index) => <article className="cms-course-card" key={item.id}>
          <div className="cms-card-arch"><span>{(item.level || "F").split(" ")[0]}</span></div><div className="cms-course-card-top"><span>{item.level}</span><span className={item.active ? "cms-active" : "cms-inactive"}>{item.active ? text.active : text.inactive}</span></div>
          <h3>{language === "ar" ? item.titleAr || item.title : item.title}</h3><p>{language === "ar" ? item.descriptionAr || item.description : item.description}</p><small>{item.lessons?.filter((lesson) => !lesson.archived).length || 0} {text.count} · #{item.order ?? index + 1}</small>
          <div className="cms-card-actions">{item.type === "cefr" && <Link to={`/admin-content/courses/${item.id}`}>{text.view} ↗</Link>}<button type="button" onClick={async () => { await mutate(`/api/admin/courses/${item.id}/status`, "PATCH", { active: !item.active }); await load(); }}>{item.active ? text.deactivate : text.activate}</button></div>
        </article>) : <p className="cms-empty">{text.noCourses}</p>}</div>
      </>}
      {mode === "course-form" && <section className="cms-editor-card"><Link className="cms-back" to="/admin-content">← {text.back}</Link><p className="cms-kicker">02 / COURSE DETAILS</p><h2>{isNewCourse ? text.create : text.edit}</h2><form className="cms-form" onSubmit={saveCourse}>
        {courseFields.map(([name, label, kind]) => <label key={name}>{label}{kind === "textarea" ? <textarea required={name === "description"} value={courseForm[name] || ""} onChange={(event) => setCourseForm({ ...courseForm, [name]: event.target.value })} /> : <input required={name === "title"} value={courseForm[name] || ""} onChange={(event) => setCourseForm({ ...courseForm, [name]: event.target.value })} />}</label>)}
        <label>{text.level}<select value={courseForm.level} onChange={(event) => setCourseForm({ ...courseForm, level: event.target.value })}>{levels.map((level) => <option key={level}>{level}</option>)}</select></label>
        <label>{text.order}<input type="number" min="0" value={courseForm.order} onChange={(event) => setCourseForm({ ...courseForm, order: event.target.value })} /></label>
        <button className="cms-primary" disabled={saving}>{saving ? text.saving : text.save}</button>
      </form></section>}
      {mode === "course" && course && <>
        <Link className="cms-back" to="/admin-content">← {text.back}</Link>
        <section className="cms-course-detail"><div className="cms-detail-medallion">{course.level}</div><div className="cms-detail-copy"><span>CEFR / {course.level}</span><h2>{language === "ar" ? course.titleAr || course.title : course.title}</h2><p>{language === "ar" ? course.descriptionAr || course.description : course.description}</p><span className={course.active ? "cms-active" : "cms-inactive"}>{course.active ? text.active : text.inactive}</span></div><div className="cms-detail-actions"><Link to={`/admin-content/courses/${course.id}/edit`}>{text.edit}</Link><button type="button" onClick={setCourseStatus}>{course.active ? text.deactivate : text.activate}</button></div></section>
        <section className="cms-lessons-panel"><div className="cms-toolbar"><div><span>LESSON PATH / {course.lessons?.length || 0}</span><h2>{text.lessons}</h2></div><Link className="cms-primary" to={`/admin-content/courses/${course.id}/lessons/new`}>＋ {text.addLesson}</Link></div>
          {visibleLessons.length ? visibleLessons.map((lesson, index) => <article className="cms-lesson-row" key={lesson.id}><div className="cms-order-buttons"><button type="button" aria-label="Move lesson up" disabled={index === 0 || saving} onClick={() => moveLesson(lesson, -1)}>↑</button><button type="button" aria-label="Move lesson down" disabled={index === visibleLessons.length - 1 || saving} onClick={() => moveLesson(lesson, 1)}>↓</button></div><span className="cms-lesson-number">{String(lesson.order || lesson.number || index + 1).padStart(2, "0")}</span><div className="cms-lesson-copy"><h3>{language === "ar" ? lesson.titleAr || lesson.title : lesson.title}</h3><p>{language === "ar" ? lesson.descriptionAr || lesson.description : lesson.description}</p><small>{lesson.estimated_minutes ? `${lesson.estimated_minutes} min` : "—"}</small></div><span className={`cms-publish-pill ${isPublished(lesson) ? "is-published" : "is-draft"}`}>{isPublished(lesson) ? text.published : text.draft}</span><Link to={`/admin-content/courses/${course.id}/lessons/${lesson.id}/edit`}>{text.edit}</Link><button type="button" disabled={saving || lesson.archived} onClick={() => setLessonStatus(lesson, { published: !isPublished(lesson) })}>{isPublished(lesson) ? text.unpublish : text.publish}</button><button className="cms-archive-action" type="button" disabled={saving} onClick={() => lesson.archived ? setLessonStatus(lesson, { archived: false }) : window.confirm(text.confirmArchive) && setLessonStatus(lesson, { archived: true })}>{lesson.archived ? text.restore : text.archive}</button></article>) : <p className="cms-empty">{text.noLessons}</p>}
          {(course.lessons || []).filter((lesson) => lesson.archived).map((lesson) => <article className="cms-lesson-row cms-archived-row" key={lesson.id}><span className="cms-lesson-number">—</span><div className="cms-lesson-copy"><h3>{lesson.title}</h3><small>{text.archive}</small></div><button type="button" onClick={() => setLessonStatus(lesson, { archived: false })}>{text.restore}</button></article>)}
        </section>
      </>}
      {mode === "lesson-form" && course && <section className="cms-editor-card cms-lesson-editor"><Link className="cms-back" to={`/admin-content/courses/${course.id}`}>← {text.lessons}</Link><p className="cms-kicker">03 / STRUCTURED LESSON</p><h2>{lessonId ? text.editLesson : text.newLesson}</h2><form className="cms-form" onSubmit={saveLesson}>
        {[["title", text.lessonTitle], ["titleAr", text.lessonTitleAr], ["description", text.lessonDescription], ["descriptionAr", text.lessonDescriptionAr]].map(([name, label]) => <label key={name}>{label}<input required={name === "title"} value={lessonForm[name] || ""} onChange={(event) => setLessonForm({ ...lessonForm, [name]: event.target.value })} /></label>)}
        <label>{text.estimated}<input type="number" min="1" max="480" value={lessonForm.estimated_minutes} onChange={(event) => setLessonForm({ ...lessonForm, estimated_minutes: event.target.value })} /></label>
        {contentFields.map((key) => <label className="cms-content-field" key={key}>{text[key]}<textarea value={lessonForm.content[key] || ""} onChange={(event) => setLessonForm({ ...lessonForm, content: { ...lessonForm.content, [key]: event.target.value } })} /></label>)}
        <p className="cms-draft-note">{text.draft}: {language === "ar" ? "الدرس الجديد غير منشور حتى يتم نشره." : "New lessons remain hidden from students until published."}</p>
        <button className="cms-primary" disabled={saving}>{saving ? text.saving : text.saveLesson}</button>
      </form></section>}
    </main>
  </div>;
}
