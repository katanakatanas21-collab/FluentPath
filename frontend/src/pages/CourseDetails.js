import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CourseNavigation from "./CourseNavigation";
import { authFetch } from "../auth";
import { courseCopy, localizedCourse } from "./courseContent";
import "./Courses.css";

function CourseDetails() {
  const { courseId } = useParams();
  const [language, setLanguage] = useState("ar");
  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const copy = courseCopy[language];

  const loadCourse = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch(`/api/courses/${courseId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || copy.errorTitle);
      setCourse(data);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [copy.errorTitle, courseId]);

  useEffect(() => { loadCourse(); }, [loadCourse]);

  if (loading) return <div className="course-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="loading-spinner" /><p>{copy.loading}</p></div>;
  if (error && !course) return <div className="course-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="course-error"><span>!</span><h2>{copy.errorTitle}</h2><p>{error}</p><button type="button" onClick={loadCourse}>{copy.retry}</button><Link to="/courses">{copy.back}</Link></div></div>;

  const item = localizedCourse(course, language);
  const lessons = course.lessons || [];
  const progress = course.progress?.percentage || 0;

  return (
    <div className="course-shell" dir={language === "ar" ? "rtl" : "ltr"}>
      <CourseNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
      <main className="course-main course-detail-main">
        <Link className="back-link" to="/courses">← {copy.back}</Link>
        <header className="detail-header"><div><p className="course-eyebrow">{copy.courseDetails} / {item.level}</p><h1>{item.displayTitle}</h1><p>{item.displayDescription}</p></div><div className="detail-progress"><strong>{progress}%</strong><span>{copy.progress}</span><div><i style={{ width: `${progress}%` }} /></div></div></header>
        {error && <div className="inline-course-error">{error}</div>}
        <section className="lesson-panel"><div className="course-section-heading"><div><span>LESSON PATH</span><h2>{copy.lessons}</h2></div><small>{course.progress?.completedCount || 0}/{course.progress?.totalLessons || lessons.length}</small></div>
          {lessons.length ? <div className="lesson-list">{lessons.map((lesson, index) => <article className={`lesson-row ${lesson.completed ? "lesson-complete" : ""}`} key={lesson.id}><span className="lesson-number">{String(lesson.order || lesson.number || index + 1).padStart(2, "0")}</span><div className="lesson-copy"><span>{copy.lesson} {lesson.order || lesson.number || index + 1}</span><h3>{language === "ar" ? lesson.titleAr || lesson.title : lesson.title}</h3><p>{language === "ar" ? lesson.descriptionAr || lesson.description || "درس متاح للطالب" : lesson.description || (typeof lesson.content === "string" ? lesson.content : "Open this lesson to start learning.")}</p></div><div className="lesson-action">{lesson.completed && <span className="lesson-status">✓ {copy.completed}</span>}<Link className="lesson-open-link" to={`/courses/${courseId}/lessons/${lesson.id}`}>{copy.openLesson} ↗</Link></div></article>)}</div> : <p className="quiet-course-message">{copy.noLessons}</p>}
        </section>
        <div className="access-note">{language === "ar" ? "محتوى الدروس متاح للطلاب المصرح لهم فقط." : "Lesson materials are available to authorized students only."}</div>
      </main>
    </div>
  );
}

export default CourseDetails;
