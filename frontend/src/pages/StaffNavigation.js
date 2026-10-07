import { Link, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../auth";
import "./StaffResponsive.css";
import { NotificationBell } from "./Notifications";

const navigation = {
  teacher: [["dashboard", "▦"], ["students", "♙"], ["courses", "◈"], ["homework", "✓"], ["classes", "◷"], ["community", "◌"], ["messages", "✉"], ["profile", "◉"]],
  administrator: [["dashboard", "▦"], ["users", "♙"], ["courses", "◈"], ["classes", "◷"], ["community", "◌"], ["reports", "⚑"], ["messages", "✉"], ["content", "▤"], ["analytics", "◔"], ["billing", "◇"], ["settings", "⚙"], ["profile", "◉"]],
};

const implementedSections = {
  teacher: ["students", "courses", "homework", "classes", "community", "messages"],
  administrator: ["users", "courses", "classes", "community", "reports", "messages", "content", "analytics"],
};

const labels = {
  teacher: { ar: { dashboard: "لوحة التحكم", students: "الطلاب", courses: "الدورات", homework: "الواجبات", classes: "الحصص", community: "المجتمع", messages: "الرسائل", profile: "الملف الشخصي", home: "الرئيسية", logout: "تسجيل الخروج", language: "English" }, en: { dashboard: "Dashboard", students: "Students", courses: "Courses", homework: "Homework", classes: "Classes", community: "Community", messages: "Messages", profile: "Profile", home: "Home", logout: "Sign out", language: "العربية" } },
  administrator: { ar: { dashboard: "لوحة التحكم", users: "المستخدمون", courses: "الدورات", classes: "الحصص", community: "إدارة المجتمع", reports: "البلاغات", messages: "رسائل الفريق", content: "المحتوى", analytics: "التحليلات", billing: "الفوترة", settings: "الإعدادات", profile: "الملف الشخصي", home: "الرئيسية", logout: "تسجيل الخروج", language: "English" }, en: { dashboard: "Dashboard", users: "Users", courses: "Courses", classes: "Classes", community: "Community management", reports: "Reports", messages: "Staff messages", content: "Content", analytics: "Analytics", billing: "Billing", settings: "Settings", profile: "Profile", home: "Home", logout: "Sign out", language: "العربية" } },
};

function StaffNavigation({ role, language, onLanguageChange }) {
  const navigate = useNavigate();
  const location = useLocation();
  const copy = labels[role][language];
  const basePath = role === "teacher" ? "/teacher-dashboard" : "/admin-dashboard";

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return <aside className="staff-sidebar">
    <Link className="staff-brand" to={basePath}><span>F</span><strong>Fluent Path</strong><small>{role === "teacher" ? (language === "ar" ? "منطقة المعلم" : "Teacher area") : (language === "ar" ? "منطقة الإدارة" : "Administrator area")}</small></Link>
    <NotificationBell language={language} />
    <Link className="staff-notifications-link" to="/notifications">{language === "ar" ? "الإشعارات" : "Notifications"}</Link>
    <div className="staff-nav-label">{language === "ar" ? "التنقل" : "Navigation"}</div>
    <nav className="staff-nav" aria-label={language === "ar" ? "التنقل" : "Navigation"}>
      {navigation[role].map(([key, icon]) => {
        const destination = key === "dashboard" ? basePath : key === "profile" ? `/${role}-profile` : role === "administrator" && key === "content" ? "/admin-content" : role === "teacher" && key === "homework" ? "/teacher-homework" : role === "teacher" && key === "classes" ? "/teacher-classes" : key === "community" ? role === "administrator" ? "/admin-community" : "/community" : key === "reports" ? "/admin-community/reports" : key === "messages" ? role === "administrator" ? "/admin-messages" : "/messages" : `${basePath}#${key}`;
        const active = key === "dashboard" ? location.pathname === basePath && !location.hash : role === "administrator" && key === "content" ? location.pathname.startsWith("/admin-content") : role === "teacher" && key === "homework" ? location.pathname.startsWith("/teacher-homework") : role === "teacher" && key === "classes" ? location.pathname.startsWith("/teacher-classes") : key === "community" ? location.pathname === (role === "administrator" ? "/admin-community" : "/community") : key === "reports" ? location.pathname === "/admin-community/reports" : key === "messages" ? location.pathname === (role === "administrator" ? "/admin-messages" : "/messages") : location.hash === `#${key}`;
        const comingSoon = !["dashboard", "profile"].includes(key) && !implementedSections[role].includes(key);
        return <Link className={active ? "active" : ""} aria-current={active ? "page" : undefined} key={key} to={destination}>
          <span aria-hidden="true">{icon}</span>{copy[key]}{comingSoon && <em>{language === "ar" ? "قريبًا" : "Soon"}</em>}
        </Link>;
      })}
    </nav>
    <div className="staff-footer">
      <button type="button" onClick={onLanguageChange}>文 {copy.language}</button>
      <Link to="/">← {copy.home}</Link>
      <button className="staff-logout" type="button" onClick={handleLogout}>↪ {copy.logout}</button>
    </div>
  </aside>;
}

export function staffLabels(role, language) {
  return labels[role][language];
}

export default StaffNavigation;
