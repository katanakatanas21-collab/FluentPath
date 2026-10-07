import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CourseNavigation from "./CourseNavigation";
import { authFetch } from "../auth";
import "./StudentLesson.css";

const lessonText = {
  ar: { back: "العودة إلى الدورة", loading: "جارٍ تحميل الدرس…", error: "تعذر تحميل الدرس", retry: "إعادة المحاولة", lesson: "الدرس", minutes: "دقيقة", introduction: "المقدمة", explanation: "الشرح", examples: "أمثلة", vocabulary: "المفردات", grammar_notes: "ملاحظات القواعد", practice_instructions: "تدريب عملي", complete: "إكمال الدرس", completed: "اكتمل الدرس", completing: "جارٍ الحفظ…", xp: "إجمالي XP", notFound: "الدرس غير متاح.", previous: "الدرس السابق", next: "الدرس التالي", course: "مسار التعلم" },
  en: { back: "Back to course", loading: "Loading lesson…", error: "Could not load lesson", retry: "Try again", lesson: "Lesson", minutes: "min", introduction: "Introduction", explanation: "Explanation", examples: "Examples", vocabulary: "Vocabulary", grammar_notes: "Grammar notes", practice_instructions: "Practice", complete: "Complete lesson", completed: "Lesson completed", completing: "Saving…", xp: "Total XP", notFound: "This lesson is unavailable.", previous: "Previous lesson", next: "Next lesson", course: "Learning path" },
};
const sectionKeys = ["introduction", "explanation", "examples", "vocabulary", "grammar_notes", "practice_instructions"];

export function LessonContent({ content, text }) {
  if (typeof content === "string") return <section className="student-lesson-section"><h2>{text.explanation}</h2><p>{content}</p></section>;
  if (!content || typeof content !== "object") return null;
  return sectionKeys.filter((key) => content[key]).map((key) => <section className="student-lesson-section" key={key}><span>{String(sectionKeys.indexOf(key) + 1).padStart(2, "0")}</span><div><h2>{text[key]}</h2><p>{content[key]}</p></div></section>);
}

export default function StudentLesson() {
  const { courseId, lessonId } = useParams();
  const [language, setLanguage] = useState("ar");
  const [course, setCourse] = useState(null);
  const [gamification, setGamification] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const text = lessonText[language];

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [courseResponse, gameResponse] = await Promise.all([authFetch(`/api/courses/${courseId}`), authFetch("/api/me/gamification")]);
      const courseData = await courseResponse.json();
      if (!courseResponse.ok) throw new Error(courseData.detail || text.error);
      const gameData = gameResponse.ok ? await gameResponse.json() : null;
      setCourse(courseData); setGamification(gameData);
    } catch (loadError) { setError(loadError.message || text.error); }
    finally { setLoading(false); }
  }, [courseId, text.error]);

  useEffect(() => { load(); }, [load]);

  const lessons = useMemo(() => [...(course?.lessons || [])].sort((a, b) => (a.order || a.number || 0) - (b.order || b.number || 0)), [course]);
  const index = lessons.findIndex((item) => item.id === lessonId);
  const lesson = index >= 0 ? lessons[index] : null;
  const completeLesson = async () => {
    if (!lesson || lesson.completed) return;
    setSaving(true); setError("");
    try {
      const response = await authFetch(`/api/me/courses/${courseId}/lessons/${lessonId}/complete`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || text.error);
      setCourse((value) => ({ ...value, progress: data.progress, lessons: value.lessons.map((item) => item.id === lessonId ? { ...item, completed: true } : item) }));
      const gameResponse = await authFetch("/api/me/gamification");
      if (gameResponse.ok) setGamification(await gameResponse.json());
    } catch (saveError) { setError(saveError.message || text.error); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="student-lesson-state" dir={language === "ar" ? "rtl" : "ltr"}>{text.loading}</div>;
  if (error && !course) return <div className="student-lesson-state" dir={language === "ar" ? "rtl" : "ltr"}><h2>{text.error}</h2><p>{error}</p><button type="button" onClick={load}>{text.retry}</button></div>;
  if (!lesson) return <div className="student-lesson-state" dir={language === "ar" ? "rtl" : "ltr"}>{text.notFound}</div>;

  const title = language === "ar" ? lesson.titleAr || lesson.title : lesson.title;
  const courseTitle = language === "ar" ? course.titleAr || course.title : course.title;
  return <div className="course-shell student-lesson-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <CourseNavigation language={language} onLanguageChange={() => setLanguage((value) => value === "ar" ? "en" : "ar")} />
    <main className="course-main student-lesson-main">
      <Link className="student-lesson-back" to={`/courses/${courseId}`}>← {text.back}</Link>
      <header className="student-lesson-hero"><div className="student-lesson-arch"><span>{String(lesson.order || lesson.number || index + 1).padStart(2, "0")}</span></div><div><p>{text.course} / {course.level}</p><h1>{title}</h1><span>{courseTitle}</span></div><div className="student-lesson-time">◷ {lesson.estimated_minutes || 15} {text.minutes}</div></header>
      <div className="student-lesson-progress"><span>{course.progress?.percentage || 0}%</span><div><i style={{ width: `${course.progress?.percentage || 0}%` }} /></div><small>{course.progress?.completedCount || 0}/{course.progress?.totalLessons || lessons.length}</small></div>
      {error && <p className="student-lesson-error" role="alert">{error}</p>}
      <article className="student-lesson-content"><div className="student-lesson-intro"><span>FLUENT PATH · {text.lesson} {index + 1}</span><h2>{language === "ar" ? lesson.descriptionAr || lesson.description : lesson.description}</h2></div><LessonContent content={lesson.content} text={text} /></article>
      <footer className="student-lesson-actions">{index > 0 ? <Link to={`/courses/${courseId}/lessons/${lessons[index - 1].id}`}>← {text.previous}</Link> : <span />}{gamification && <span className="student-lesson-xp">✦ {gamification.xp} {text.xp}</span>}{lesson.completed ? <span className="student-lesson-done">✓ {text.completed}</span> : <button type="button" disabled={saving} onClick={completeLesson}>{saving ? text.completing : text.complete}</button>}{index < lessons.length - 1 && <Link to={`/courses/${courseId}/lessons/${lessons[index + 1].id}`}>{text.next} →</Link>}</footer>
    </main>
  </div>;
}
