import { Link, useNavigate } from "react-router-dom";
import { logout } from "../auth";
import { courseCopy } from "./courseContent";
import { NotificationBell } from "./Notifications";

function CourseNavigation({ language, onLanguageChange, activePage = "courses" }) {
  const navigate = useNavigate();
  const copy = courseCopy[language];

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <aside className="course-sidebar">
      <Link className="course-brand" to="/student-dashboard">
        <span className="course-brand-mark">F</span>
        <span><strong>Fluent Path</strong><small>{copy.coursePath}</small></span>
      </Link>
      <NotificationBell language={language} />
      <Link to="/notifications">♧ {language === "ar" ? "الإشعارات" : "Notifications"}</Link>
      <nav className="course-nav" aria-label={copy.coursePath}>
        <Link className={activePage === "dashboard" ? "active" : ""} to="/student-dashboard"><span aria-hidden="true">▦</span>{copy.dashboard}</Link>
        <Link className={activePage === "courses" ? "active" : ""} to="/courses"><span aria-hidden="true">◈</span>{copy.courses}</Link>
        <Link className={activePage === "ai-teacher" ? "active" : ""} to="/ai-teacher"><span aria-hidden="true">✦</span>{language === "ar" ? "معلم الذكاء الاصطناعي" : "AI Teacher"}</Link>
        <Link className={activePage === "homework" ? "active" : ""} to="/homework"><span aria-hidden="true">✓</span>{copy.homework}</Link>
        <Link to="/achievements"><span aria-hidden="true">★</span>{language === "ar" ? "الإنجازات" : "Achievements"}</Link>
        <Link to="/profile"><span aria-hidden="true">◉</span>{language === "ar" ? "الملف الشخصي" : "Profile"}</Link>
      </nav>
      <div className="course-nav-footer">
        <button type="button" onClick={onLanguageChange}><span aria-hidden="true">文</span>{copy.language}</button>
        <Link to="/">← {copy.home}</Link>
        <button className="course-logout" type="button" onClick={handleLogout}>↪ {language === "ar" ? "تسجيل الخروج" : "Sign out"}</button>
      </div>
    </aside>
  );
}

export default CourseNavigation;
