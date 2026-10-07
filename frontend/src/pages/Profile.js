import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CourseNavigation from "./CourseNavigation";
import { authFetch } from "../auth";
import "./Courses.css";

function Profile() {
  const [language, setLanguage] = useState("ar");
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const ar = language === "ar";

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      const response = await authFetch("/api/profile");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load profile");
      setUser(data);
    } catch (profileError) {
      setError(profileError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  if (loading) return <div className="course-state"><div className="loading-spinner" /><p>{ar ? "جارٍ تحميل الملف الشخصي..." : "Loading your profile..."}</p></div>;
  if (error) return <div className="course-state"><div className="course-error"><span>!</span><h2>{ar ? "تعذر تحميل الملف الشخصي" : "Could not load your profile"}</h2><p>{error}</p><button type="button" onClick={loadProfile}>{ar ? "إعادة المحاولة" : "Try again"}</button></div></div>;

  return <div className="course-shell" dir={ar ? "rtl" : "ltr"}><CourseNavigation language={language} onLanguageChange={() => setLanguage(ar ? "en" : "ar")} /><main className="course-main"><p className="course-eyebrow">FLUENT PATH / PROFILE</p><h1>{ar ? "الملف الشخصي" : "Profile"}</h1><section className="detail-header" style={{ marginTop: "25px" }}><div><p className="course-eyebrow">{ar ? "المعلومات الشخصية" : "Personal information"}</p><h2>{user.fullName}</h2><p>{user.email}</p></div><div className="detail-progress"><strong>{user.role}</strong><span>{ar ? "الدور" : "Role"}</span></div></section><Link className="achievement-back-link" to="/achievements">★ {ar ? "عرض إنجازاتي" : "View my achievements"} ↗</Link></main></div>;
}

export default Profile;
