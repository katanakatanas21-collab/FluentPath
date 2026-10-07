import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StaffNavigation from "./StaffNavigation";
import { authFetch } from "../auth";
import "./StaffDashboard.css";

function StaffProfile({ role }) {
  const staffRole = role === "administrator" ? "administrator" : "teacher";
  const [language, setLanguage] = useState("ar");
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const copy = language === "ar" ? { title: "الملف الشخصي", details: "بيانات الحساب", role: "الدور", home: "العودة إلى لوحة التحكم" } : { title: "Profile", details: "Account details", role: "Role", home: "Back to dashboard" };

  const loadProfile = useCallback(async () => {
    try {
      const response = await authFetch("/api/profile");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load profile");
      setUser(data);
    } catch (loadError) {
      setError(loadError.message);
    }
  }, []);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  if (error) return <div className="staff-state"><div className="staff-state-card"><span>!</span><h2>{error}</h2></div></div>;
  if (!user) return <div className="staff-state"><div className="loading-spinner" /></div>;

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}><StaffNavigation role={staffRole} language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} /><main className="staff-main"><header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / PROFILE</p><h1>{copy.title}</h1></div><div className="staff-account"><span>{user.fullName.charAt(0)}</span><div><strong>{user.fullName}</strong><small>{user.email}</small></div></div></header><section className="staff-panel"><div className="staff-panel-heading"><div><span>ACCOUNT</span><h2>{copy.details}</h2></div></div><div className="course-mini-list"><div className="course-mini"><strong>{user.fullName}</strong><small>{user.email}</small></div><div className="course-mini"><strong>{copy.role}</strong><small>{user.role}</small></div></div><Link className="role-home" to={staffRole === "teacher" ? "/teacher-dashboard" : "/admin-dashboard"}>{copy.home}</Link></section></main></div>;
}

export default StaffProfile;
