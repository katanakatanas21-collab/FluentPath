import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch } from "../auth";
import CourseNavigation from "./CourseNavigation";
import { BadgeCard, LevelProgress, StreakCard, XPCard } from "./GamificationComponents";
import "./Courses.css";
import "./Gamification.css";

function AchievementsPage() {
  const [language, setLanguage] = useState("ar");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const ar = language === "ar";
  const loadAchievements = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/me/achievements");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || (ar ? "تعذر تحميل الإنجازات." : "Could not load achievements."));
      setData(payload);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [ar]);

  useEffect(() => { loadAchievements(); }, [loadAchievements]);

  return <div className="course-shell" dir={ar ? "rtl" : "ltr"}>
    <CourseNavigation language={language} onLanguageChange={() => setLanguage(ar ? "en" : "ar")} />
    <main className="course-main">
      <p className="course-eyebrow">FLUENT PATH / ACHIEVEMENTS</p>
      <h1>{ar ? "الإنجازات" : "Achievements"}</h1>
      <p className="course-subtitle">{ar ? "تابع نقاط الخبرة والشارات وسلسلة تعلمك." : "Track your XP, badges, and learning streak."}</p>
      {loading ? <div className="course-state"><div className="loading-spinner" /><p>{ar ? "جارٍ تحميل الإنجازات..." : "Loading achievements..."}</p></div> : error ? <div className="course-error" role="alert"><span>!</span><h2>{ar ? "تعذر تحميل الإنجازات" : "Could not load achievements"}</h2><p>{error}</p><button type="button" onClick={loadAchievements}>{ar ? "إعادة المحاولة" : "Try again"}</button></div> : <>
        <section className="gamification-dashboard-grid achievement-overview">
          <XPCard data={data} language={language} />
          <LevelProgress data={data} language={language} />
          <StreakCard data={data} language={language} />
        </section>
        <section className="gamification-card"><div className="gamification-section-heading"><h2>{ar ? "الشارات" : "Badges"}</h2><span>{data.badges.filter((badge) => badge.earned).length}/{data.badges.length}</span></div><div className="achievement-page-grid">{data.badges.map((badge) => <BadgeCard key={badge.id} badge={badge} language={language} />)}</div></section>
        <Link className="achievement-back-link" to="/student-dashboard">← {ar ? "العودة إلى لوحة التحكم" : "Back to dashboard"}</Link>
      </>}
    </main>
  </div>;
}

export default AchievementsPage;
