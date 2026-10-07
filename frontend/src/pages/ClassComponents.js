import { Link, useNavigate } from "react-router-dom";
import { logout } from "../auth";

const studentNavigation = {
  ar: { dashboard: "لوحة التحكم", courses: "دوراتي", homework: "واجباتي", schedule: "الجدول", profile: "الملف الشخصي", home: "الرئيسية", signOut: "تسجيل الخروج", language: "English" },
  en: { dashboard: "Dashboard", courses: "Courses", homework: "Homework", schedule: "Schedule", profile: "Profile", home: "Home", signOut: "Sign out", language: "العربية" },
};

export function ClassNavigation({ language, onLanguageChange }) {
  const navigate = useNavigate();
  const copy = studentNavigation[language];
  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return <aside className="class-sidebar">
    <Link className="class-brand" to="/student-dashboard"><span>F</span><strong>Fluent Path</strong><small>{language === "ar" ? "مساحة الطالب" : "Student space"}</small></Link>
    <nav aria-label={language === "ar" ? "التنقل" : "Navigation"}>
      <Link to="/student-dashboard">▦ {copy.dashboard}</Link><Link to="/courses">◈ {copy.courses}</Link><Link to="/ai-teacher">✦ {language === "ar" ? "معلم الذكاء الاصطناعي" : "AI Teacher"}</Link><Link to="/homework">✓ {copy.homework}</Link><Link className="active" to="/schedule">◷ {copy.schedule}</Link><Link to="/profile">◉ {copy.profile}</Link>
    </nav>
    <div className="class-sidebar-footer"><button type="button" onClick={onLanguageChange}>文 {copy.language}</button><Link to="/">← {copy.home}</Link><button className="class-signout" type="button" onClick={handleLogout}>↪ {copy.signOut}</button></div>
  </aside>;
}

export function formatClassDate(classItem, language, withTime = true) {
  if (!classItem) return "—";
  const value = classItem.startsAt || `${classItem.date || ""}T${classItem.startTime || "00:00"}`;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return `${classItem.date || ""} ${classItem.startTime || ""}`.trim() || "—";
  return new Intl.DateTimeFormat(language === "ar" ? "ar" : "en", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(parsed);
}

export function ClassStatus({ classItem, language }) {
  const status = classItem?.status || "scheduled";
  const label = language === "ar"
    ? { scheduled: "مجدولة", cancelled: "ملغاة", completed: "مكتملة" }[status] || status
    : { scheduled: "Scheduled", cancelled: "Cancelled", completed: "Completed" }[status] || status;
  return <span className={`class-status class-status-${status}`}>{label}</span>;
}

export function ClassCard({ classItem, language }) {
  const title = classItem.title;
  const courseTitle = language === "ar" ? classItem.course?.titleAr || classItem.course?.title : classItem.course?.title;
  return <Link className="class-card" to={`/classes/${classItem.id}`}>
    <div className="class-card-top"><ClassStatus classItem={classItem} language={language} /><time>{formatClassDate(classItem, language)}</time></div>
    <h2>{title}</h2><p>{classItem.description || courseTitle || classItem.level || "—"}</p>
    <div className="class-card-bottom"><span>{courseTitle || classItem.level || (language === "ar" ? "حصة مباشرة" : "Live class")}</span><span>↗</span></div>
  </Link>;
}

export function ClassState({ language, loading = false, error, onRetry, children }) {
  return <div className="class-state" role={error ? "alert" : undefined}><span>{error ? "!" : loading ? "F" : "◷"}</span><p>{error || children}</p>{error && onRetry && <button type="button" onClick={onRetry}>{language === "ar" ? "إعادة المحاولة" : "Try again"}</button>}</div>;
}

