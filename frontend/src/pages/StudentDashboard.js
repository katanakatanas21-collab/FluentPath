import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { authFetch, logout } from "../auth";
import { AchievementSection, Leaderboard, LevelProgress, StreakCard, XPCard } from "./GamificationComponents";
import "./StudentDashboard.css";
import { NotificationBell } from "./Notifications";

const translations = {
  ar: {
    dashboard: "لوحة التحكم", overview: "نظرة عامة على رحلتك التعليمية", welcome: "مرحبًا بعودتك", home: "الرئيسية", studentArea: "مساحة الطالب",
    level: "المستوى الحالي", score: "نتيجة الاختبار", progress: "التقدم العام", streak: "سلسلة التعلم", days: "يوم", noResult: "لم يتم إجراء الاختبار بعد",
    journey: "رحلتي التعليمية", courses: "الدورات", homework: "واجباتي", schedule: "الجدول الدراسي", recentActivity: "النشاط الأخير", placementTest: "اختبار تحديد المستوى",
    completed: "مكتمل", noActivity: "لا يوجد نشاط حديث بعد.", noCourses: "لا توجد دورات قيد الدراسة بعد.", coursesMvp: "استكشف الدورات المتاحة وابدأ درسًا جديدًا.",
    homeworkMvp: "لا توجد واجبات مسندة إليك حاليًا.", scheduleMvp: "لا توجد حصص قادمة مسندة إليك حاليًا.", upcomingClasses: "الحصص القادمة", mvp: "قريبًا",
    navigation: "التنقل", myCourses: "الدورات", community: "المجتمع", messages: "الرسائل", achievements: "الإنجازات", profile: "الملف الشخصي", retry: "إعادة المحاولة", viewHomework: "عرض الواجبات", viewSchedule: "عرض الجدول", browseCourses: "استكشف الدورات", sectionsError: "تعذر تحميل بعض أقسام لوحة التحكم. أعد المحاولة.",
    longestStreak: "أطول سلسلة", aiTeacher: "معلم الذكاء الاصطناعي", aiQuickAction: "ابدأ تدريبًا شخصيًا مع معلم الذكاء الاصطناعي",
    createAccount: "إنشاء حساب", errorTitle: "تعذر تحميل لوحة التحكم", loading: "جارٍ تحميل لوحة الطالب...", testAgain: "إعادة اختبار المستوى", english: "English", arabic: "العربية", logout: "تسجيل الخروج",
  },
  en: {
    dashboard: "Dashboard", overview: "A clear view of your learning journey", welcome: "Welcome back", home: "Home", studentArea: "Student space",
    level: "Current level", score: "Test score", progress: "Overall progress", streak: "Learning streak", days: "days", noResult: "Take the placement test to see your level",
    journey: "My learning journey", courses: "Courses", homework: "Homework", schedule: "Schedule", recentActivity: "Recent activity", placementTest: "Placement test",
    completed: "Completed", noActivity: "No recent activity yet.", noCourses: "You have no courses in progress yet.", coursesMvp: "Explore the available courses and start a lesson.",
    homeworkMvp: "No homework has been assigned to you yet.", scheduleMvp: "No upcoming classes have been assigned to you yet.", upcomingClasses: "Upcoming classes", mvp: "Coming soon",
    navigation: "Navigation", myCourses: "Courses", community: "Community", messages: "Messages", achievements: "Achievements", profile: "Profile", retry: "Try again", viewHomework: "View homework", viewSchedule: "View schedule", browseCourses: "Browse courses", sectionsError: "Some dashboard sections could not be loaded. Try again.",
    longestStreak: "Longest streak", aiTeacher: "AI Teacher", aiQuickAction: "Start a personalized practice session",
    createAccount: "Create an account", errorTitle: "Could not load your dashboard", loading: "Loading your dashboard...", testAgain: "Retake placement test", english: "العربية", arabic: "English", logout: "Sign out",
  },
};

const navigationItems = [
  ["dashboard", "▦"], ["myCourses", "◈"], ["aiTeacher", "✦"], ["homework", "✓"], ["schedule", "◷"],
  ["community", "◌"], ["messages", "✉"], ["achievements", "★"], ["profile", "◉"],
];

function Sidebar({ language, onLanguageChange, onLogout }) {
  const copy = translations[language];
  return (
    <aside className="dashboard-sidebar">
      <NotificationBell language={language} />
      <Link className="sidebar-link" to="/notifications">♧ {language === "ar" ? "الإشعارات" : "Notifications"}</Link>
      <div className="brand-lockup"><div className="brand-mark">F</div><div><strong>Fluent Path</strong><span>{copy.studentArea}</span></div></div>
      <div className="sidebar-section-label">{copy.navigation}</div>
      <nav className="sidebar-nav" aria-label={copy.navigation}>
        {navigationItems.map(([key, icon]) => {
          const content = <><span className="sidebar-icon" aria-hidden="true">{icon}</span><span>{copy[key]}</span></>;
          if (["aiTeacher", "homework", "schedule", "community", "messages", "achievements"].includes(key)) {
            const paths = { aiTeacher: "/ai-teacher", homework: "/homework", schedule: "/schedule", community: "/community", messages: "/messages", achievements: "/achievements" };
            return <Link className="sidebar-link" to={paths[key]} key={key} title={copy[key]}>{content}</Link>;
          }
          if (key === "dashboard" || key === "myCourses" || key === "profile") {
            const paths = { dashboard: "/student-dashboard", myCourses: "/courses", profile: "/profile" };
            return <Link className={`sidebar-link ${key === "dashboard" ? "active" : ""}`} to={paths[key]} key={key} title={copy[key]}>
            {content}
            </Link>;
          }
          return null;
        })}
      </nav>
      <div className="sidebar-footer">
        <button className="language-switcher" onClick={onLanguageChange} type="button"><span aria-hidden="true">文</span>{language === "ar" ? copy.english : copy.arabic}</button>
        <Link className="sidebar-home-link" to="/">← {copy.home}</Link>
        <button className="sidebar-logout" onClick={onLogout} type="button">↪ {copy.logout}</button>
      </div>
    </aside>
  );
}

function StatCard({ icon, label, value, detail, tone }) {
  return <article className={`stat-card ${tone}`}><div className="stat-card-top"><span className="stat-icon" aria-hidden="true">{icon}</span><span className="stat-label">{label}</span></div><strong className="stat-value">{value}</strong><span className="stat-detail">{detail}</span></article>;
}

function EmptyPanel({ icon, title, description, badge }) {
  return <div className="empty-panel"><span className="empty-icon" aria-hidden="true">{icon}</span><div><h3>{title}</h3><p>{description}</p></div>{badge && <span className="mvp-badge">{badge}</span>}</div>;
}

function formatActivityDate(dateValue, language) {
  if (!dateValue) return "";
  return new Intl.DateTimeFormat(language === "ar" ? "ar" : "en", { day: "numeric", month: "short", year: "numeric" }).format(new Date(dateValue));
}

function StudentDashboard() {
  const navigate = useNavigate();
  const [student, setStudent] = useState(null);
  const [homework, setHomework] = useState([]);
  const [schedule, setSchedule] = useState([]);
  const [gamification, setGamification] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [secondaryError, setSecondaryError] = useState(false);
  const [language, setLanguage] = useState("ar");
  const copy = translations[language];

  const loadStudent = async () => {
    setLoading(true);
    setError("");
    setSecondaryError(false);
    try {
      const response = await authFetch("/api/me");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "تعذر تحميل بيانات الطالب.");
      setStudent(data);
      try {
        const [gamificationResponse, leaderboardResponse] = await Promise.all([
          authFetch("/api/me/gamification"),
          authFetch("/api/leaderboard"),
        ]);
        const [gamificationData, leaderboardData] = await Promise.all([
          gamificationResponse.json(), leaderboardResponse.json(),
        ]);
        if (!gamificationResponse.ok || !leaderboardResponse.ok) setSecondaryError(true);
        setGamification(gamificationResponse.ok ? gamificationData : null);
        setLeaderboard(leaderboardResponse.ok ? leaderboardData.leaderboard || [] : []);
      } catch {
        setGamification(null);
        setLeaderboard([]);
        setSecondaryError(true);
      }
      try {
        const homeworkResponse = await authFetch("/api/student/homework");
        const homeworkData = await homeworkResponse.json();
        if (!homeworkResponse.ok) setSecondaryError(true);
        setHomework(homeworkResponse.ok ? homeworkData.homework || [] : []);
      } catch {
        setHomework([]);
        setSecondaryError(true);
      }
      try {
        const scheduleResponse = await authFetch("/api/student/classes");
        const scheduleData = await scheduleResponse.json();
        if (!scheduleResponse.ok) setSecondaryError(true);
        setSchedule(scheduleResponse.ok ? scheduleData.upcoming || [] : []);
      } catch {
        setSchedule([]);
        setSecondaryError(true);
      }
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  useEffect(() => { loadStudent(); }, []);

  if (loading) return <div className="dashboard-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="loading-spinner" /><p>{copy.loading}</p></div>;
  if (error) return <div className="dashboard-state" dir={language === "ar" ? "rtl" : "ltr"}><div className="state-card"><span className="state-symbol">!</span><h2>{copy.errorTitle}</h2><p>{error}</p><button className="primary-button" onClick={loadStudent} type="button">{copy.retry}</button><Link className="state-link" to="/register">{copy.createAccount}</Link></div></div>;

  const scoreAvailable = Number.isFinite(student.testScore) && Number.isFinite(student.totalQuestions) && student.totalQuestions > 0;
  const scorePercent = scoreAvailable ? Math.round((student.testScore / student.totalQuestions) * 100) : 0;
  const activityDate = formatActivityDate(student.testCompletedAt, language);

  return (
    <div className="dashboard-shell" dir={language === "ar" ? "rtl" : "ltr"} id="dashboard">
      <Sidebar language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} onLogout={handleLogout} />
      <main className="dashboard-main">
        {secondaryError && <div role="alert" className="dashboard-load-warning">{copy.sectionsError} <button type="button" onClick={loadStudent}>{copy.retry}</button></div>}
        <header className="dashboard-header"><div><p className="eyebrow">{copy.dashboard}</p><h1>{copy.welcome}, {student.fullName.split(" ")[0]}</h1><p className="header-subtitle">{copy.overview}</p></div><div className="account-chip"><span className="avatar">{student.fullName.charAt(0).toUpperCase()}</span><span><strong>{student.fullName}</strong><small>{student.email}</small></span></div></header>
        <section className="welcome-banner"><div><span className="banner-kicker">FLUENT PATH / 2026</span><h2>{copy.journey}</h2><p>{scoreAvailable ? `${copy.completed} · ${student.level}` : copy.noResult}</p><Link className="ai-teacher-quick-action" to="/ai-teacher">✦ {copy.aiQuickAction} ↗</Link></div><div className="banner-orbit" aria-hidden="true"><span>F</span></div></section>
        <section className="stats-grid" aria-label={copy.overview}>
          <StatCard icon="◎" label={copy.level} value={student.level || "—"} detail={student.level ? "CEFR" : copy.noResult} tone="blue" />
          <StatCard icon="↗" label={copy.score} value={scoreAvailable ? `${student.testScore}/${student.totalQuestions}` : "—"} detail={scoreAvailable ? `${scorePercent}%` : copy.noResult} tone="coral" />
          <StatCard icon="◔" label={copy.progress} value={`${scorePercent}%`} detail={scoreAvailable ? copy.placementTest : copy.noResult} tone="mint" />
          <StatCard icon="✦" label={copy.streak} value={gamification?.currentStreak || 0} detail={`${copy.longestStreak}: ${gamification?.longestStreak || 0}`} tone="gold" />
        </section>
        <section className="gamification-dashboard-grid" aria-label={copy.achievements}>
          <XPCard data={gamification || {}} language={language} />
          <LevelProgress data={gamification || {}} language={language} />
          <StreakCard data={gamification || {}} language={language} />
          <AchievementSection badges={gamification?.recentAchievements || []} language={language} />
          <Leaderboard entries={leaderboard} language={language} preview />
        </section>
        <div className="content-grid">
          <section className="dashboard-panel activity-panel"><div className="panel-heading"><div><span className="panel-kicker">01 / ACTIVITY</span><h2>{copy.recentActivity}</h2></div><span className="panel-count">{activityDate || "—"}</span></div>{activityDate ? <div className="activity-row"><span className="activity-check">✓</span><div><strong>{copy.placementTest}</strong><p>{copy.completed} · {activityDate}</p></div><span className="activity-score">{student.testScore}/{student.totalQuestions}</span></div> : <p className="quiet-message">{copy.noActivity}</p>}</section>
          <section className="dashboard-panel courses-panel"><div className="panel-heading"><div><span className="panel-kicker">02 / LEARNING</span><h2>{copy.courses}</h2></div><Link className="panel-count panel-link" to="/courses">↗</Link></div><EmptyPanel icon="◈" title={copy.noCourses} description={copy.coursesMvp} /><Link className="dashboard-homework-all" to="/courses">{copy.browseCourses} ↗</Link></section>
        </div>
        <div className="content-grid lower-grid">
          <section className="dashboard-panel"><div className="panel-heading"><div><span className="panel-kicker">03 / PRACTICE</span><h2>{copy.homework}</h2></div><Link className="panel-count panel-link" to="/homework">{homework.length}</Link></div>{homework.length ? <div className="dashboard-homework-list">{homework.slice(0, 3).map((item) => <Link to={`/homework/${item.id}`} key={item.id}><strong>{item.title}</strong><span>{item.submission?.status || (language === "ar" ? "جديد" : "New")}</span></Link>)}<Link className="dashboard-homework-all" to="/homework">{copy.viewHomework} ↗</Link></div> : <EmptyPanel icon="✓" title={copy.homework} description={copy.homeworkMvp} />}</section>
          <section className="dashboard-panel"><div className="panel-heading"><div><span className="panel-kicker">04 / PLAN</span><h2>{copy.upcomingClasses}</h2></div><Link className="panel-count panel-link" to="/schedule">{schedule.length}</Link></div>{schedule.length ? <div className="dashboard-homework-list">{schedule.slice(0, 3).map((item) => <Link to={`/classes/${item.id}`} key={item.id}><strong>{item.title}</strong><span>{formatActivityDate(item.startsAt, language)}</span></Link>)}<Link className="dashboard-homework-all" to="/schedule">{copy.viewSchedule} ↗</Link></div> : <EmptyPanel icon="◷" title={copy.schedule} description={copy.scheduleMvp} />}</section>
        </div>
        <footer className="dashboard-footer"><Link to="/trial-test">{copy.testAgain} ↗</Link><span>{student.email}</span></footer>
      </main>
    </div>
  );
}

export default StudentDashboard;
