import { useCallback, useEffect, useState } from "react";
import CourseCard from "./CourseCard";
import CourseNavigation from "./CourseNavigation";
import { authFetch } from "../auth";
import { courseCopy } from "./courseContent";
import "./Courses.css";

function Courses() {
  const [language, setLanguage] = useState("ar");
  const [courses, setCourses] = useState([]);
  const [student, setStudent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const copy = courseCopy[language];

  const loadCourses = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [coursesResponse, studentResponse] = await Promise.all([
        authFetch("/api/courses"),
        authFetch("/api/me"),
      ]);
      const coursesData = await coursesResponse.json();
      const studentData = await studentResponse.json();
      if (!coursesResponse.ok) throw new Error(coursesData.detail || copy.errorTitle);
      if (!studentResponse.ok) throw new Error(studentData.detail || copy.errorTitle);
      setCourses(coursesData.courses || []);
      setStudent(studentData);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [copy.errorTitle]);

  useEffect(() => { loadCourses(); }, [loadCourses]);

  if (loading) return <div className="course-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="loading-spinner" /><p>{copy.loading}</p></div>;
  if (error) return <div className="course-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="course-error"><span>!</span><h2>{copy.errorTitle}</h2><p>{error}</p><button type="button" onClick={loadCourses}>{copy.retry}</button></div></div>;

  const cefrCourses = courses.filter((course) => course.type === "cefr");
  const futureCourses = courses.filter((course) => course.type === "future");
  const availableCount = cefrCourses.filter((course) => course.available).length;

  return (
    <div className="course-shell" dir={language === "ar" ? "rtl" : "ltr"}>
      <CourseNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
      <main className="course-main">
        <header className="course-header"><div><p className="course-eyebrow">FLUENT PATH / LEARNING</p><h1>{copy.courses}</h1><p>{copy.overview}</p></div><div className="course-account"><span>{student?.fullName?.charAt(0).toUpperCase()}</span><div><strong>{student?.fullName}</strong><small>{student?.level || "—"}</small></div></div></header>
        <section className="course-hero"><div><span>{copy.coursePath}</span><h2>{student?.level ? `${student.level} · ${availableCount} ${language === "ar" ? "دورات متاحة" : "courses available"}` : copy.overview}</h2><p>{copy.overview}</p></div><div className="path-badge" aria-hidden="true">A0 <i>→</i> C1+</div></section>
        <section className="course-section"><div className="course-section-heading"><div><span>01 / CEFR</span><h2>{copy.coursePath}</h2></div><small>{cefrCourses.length} {language === "ar" ? "مستويات" : "levels"}</small></div><div className="course-grid">{cefrCourses.map((course) => <CourseCard course={course} language={language} key={course.id} />)}</div></section>
        <section className="course-section future-section"><div className="course-section-heading"><div><span>02 / EXPLORE</span><h2>{copy.futureTitle}</h2><p>{copy.futureDescription}</p></div><small>{futureCourses.length}</small></div><div className="course-grid future-grid">{futureCourses.map((course) => <CourseCard course={course} language={language} key={course.id} />)}</div></section>
      </main>
    </div>
  );
}

export default Courses;
