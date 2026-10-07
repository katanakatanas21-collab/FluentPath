import { Link } from "react-router-dom";
import { localizedCourse, formatProgress } from "./courseContent";

function CourseCard({ course, language }) {
  const copy = language === "ar"
    ? { level: "المستوى", lessons: "دروس", locked: "مقفل", available: "متاح الآن", comingSoon: "قريبًا", open: "فتح الدورة" }
    : { level: "Level", lessons: "lessons", locked: "Locked", available: "Available now", comingSoon: "Coming soon", open: "Open course" };
  const item = localizedCourse(course, language);
  const progress = formatProgress(course.progress);
  const isFuture = course.type === "future";

  const card = (
    <article className={`course-card ${course.locked ? "course-locked" : ""} ${isFuture ? "course-future" : ""}`}>
      <div className="course-card-top"><span className="course-type">{isFuture ? "PROGRAM" : "CEFR PATH"}</span><span className="course-status">{course.locked ? "▣ " + copy.locked : isFuture ? copy.comingSoon : copy.available}</span></div>
      <div className="course-level">{item.level}</div>
      <h3>{item.displayTitle}</h3>
      <p>{item.displayDescription}</p>
      {!isFuture && <div className="course-progress"><div className="course-progress-label"><span>{copy.level} {item.level}</span><strong>{progress}%</strong></div><div className="course-progress-track"><span style={{ width: `${progress}%` }} /></div><small>{course.lessonCount} {copy.lessons}</small></div>}
      {isFuture && <span className="future-note">{copy.comingSoon}</span>}
      {!course.locked && !isFuture && <span className="course-open">{copy.open} <span aria-hidden="true">↗</span></span>}
    </article>
  );

  return course.available && !isFuture ? <Link className="course-card-link" to={`/courses/${course.id}`}>{card}</Link> : card;
}

export default CourseCard;
