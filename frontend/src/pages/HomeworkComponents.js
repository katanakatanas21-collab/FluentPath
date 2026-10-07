import { Link, useNavigate } from "react-router-dom";
import { logout } from "../auth";
import { NotificationBell } from "./Notifications";

const navigationCopy = {
  ar: { dashboard: "لوحة التحكم", courses: "دوراتي", homework: "واجباتي", profile: "الملف الشخصي", home: "الرئيسية", signOut: "تسجيل الخروج", language: "English", area: "مساحة الطالب" },
  en: { dashboard: "Dashboard", courses: "My courses", homework: "Homework", profile: "Profile", home: "Home", signOut: "Sign out", language: "العربية", area: "Student space" },
};

export function HomeworkNavigation({ language, onLanguageChange, active = "homework" }) {
  const navigate = useNavigate();
  const copy = navigationCopy[language];
  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return <aside className="homework-sidebar">
    <NotificationBell language={language} />
    <Link to="/notifications">♧ {language === "ar" ? "الإشعارات" : "Notifications"}</Link>
    <Link className="homework-brand" to="/student-dashboard"><span>F</span><strong>Fluent Path</strong><small>{copy.area}</small></Link>
    <nav aria-label={copy.area}>
      <Link to="/student-dashboard">▦ {copy.dashboard}</Link>
      <Link to="/courses">◈ {copy.courses}</Link>
      <Link className={active === "ai-teacher" ? "active" : ""} to="/ai-teacher">✦ {language === "ar" ? "معلم الذكاء الاصطناعي" : "AI Teacher"}</Link>
      <Link className={active === "homework" ? "active" : ""} to="/homework">✓ {copy.homework}</Link>
      <Link className={active === "community" ? "active" : ""} to="/community">◌ {language === "ar" ? "المجتمع" : "Community"}</Link>
      <Link className={active === "messages" ? "active" : ""} to="/messages">✉ {language === "ar" ? "الرسائل" : "Messages"}</Link>
      <Link to="/profile">◉ {copy.profile}</Link>
    </nav>
    <div className="homework-sidebar-footer">
      <button type="button" onClick={onLanguageChange}>文 {copy.language}</button>
      <Link to="/">← {copy.home}</Link>
      <button className="homework-signout" type="button" onClick={handleLogout}>↪ {copy.signOut}</button>
    </div>
  </aside>;
}

export function HomeworkStatus({ status, language }) {
  const labels = language === "ar"
    ? { assigned: "جديد", published: "جديد", submitted: "تم التسليم", late: "تم التسليم متأخرًا", graded: "تم التقييم" }
    : { assigned: "Assigned", published: "Assigned", submitted: "Submitted", late: "Submitted late", graded: "Graded" };
  return <span className={`homework-status status-${status || "assigned"}`}>{labels[status] || labels.assigned}</span>;
}

export function HomeworkCard({ homework, language }) {
  const courseName = language === "ar" ? homework.course?.titleAr || homework.course?.title : homework.course?.title;
  const dueDate = homework.dueDate
    ? new Intl.DateTimeFormat(language === "ar" ? "ar" : "en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(homework.dueDate))
    : language === "ar" ? "لا يوجد موعد نهائي" : "No due date";
  return <Link className="homework-card" to={`/homework/${homework.id}`}>
    <div className="homework-card-top"><HomeworkStatus status={homework.submission?.status || homework.status} language={language} /><time dateTime={homework.dueDate || undefined}>{dueDate}</time></div>
    <h2>{homework.title}</h2>
    <p>{homework.description}</p>
    <div className="homework-card-meta">{courseName || homework.level || (language === "ar" ? "واجب" : "Homework")} <span>↗</span></div>
  </Link>;
}

export function HomeworkState({ language, error, onRetry, children }) {
  return <div className="homework-state" role={error ? "alert" : undefined}>
    <span>{error ? "!" : "F"}</span>
    <p>{error || children}</p>
    {error && onRetry && <button type="button" onClick={onRetry}>{language === "ar" ? "إعادة المحاولة" : "Try again"}</button>}
  </div>;
}
