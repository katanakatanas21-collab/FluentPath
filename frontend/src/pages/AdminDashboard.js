import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StaffNavigation from "./StaffNavigation";
import { MvpNotice, StaffStat, StaffState } from "./StaffComponents";
import { authFetch } from "../auth";
import { ClassStatus, formatClassDate } from "./ClassComponents";
import "./Class.css";
import "./ClassStaff.css";
import "./StaffDashboard.css";

const translations = {
  ar: { title: "لوحة الإدارة", subtitle: "نظرة موحدة على مستخدمي ومنتجات Fluent Path.", welcome: "منصة Fluent Path", overview: "إدارة المستخدمين والمحتوى من مكان واحد.", students: "الطلاب", teachers: "المعلمون", courses: "الدورات", activity: "الدروس المكتملة", recent: "المستخدمون", courseManagement: "إدارة الدورات", users: "مستخدمون", lessons: "دروس", homework: "الواجبات", classes: "الحصص", noClasses: "لا توجد حصص.", upcoming: "قادمة", past: "سابقة", cancelled: "ملغاة", noUsers: "لا يوجد مستخدمون.", noCourses: "لا توجد دورات.", contentAction: "إدارة الدورات والدروس", billingNote: "الفوترة والاشتراكات غير متاحة بعد.", settingsNote: "إعدادات المنصة غير متاحة بعد.", role: "الدور", assigned: "طلاب" },
  en: { title: "Administrator Dashboard", subtitle: "A unified view of Fluent Path users and products.", welcome: "Fluent Path platform", overview: "Manage users and content from one place.", students: "Students", teachers: "Teachers", courses: "Courses", activity: "Completed lessons", recent: "Users", courseManagement: "Course management", users: "users", lessons: "lessons", homework: "Homework", classes: "Classes", noClasses: "No classes found.", upcoming: "Upcoming", past: "Past", cancelled: "Cancelled", noUsers: "No users yet.", noCourses: "No courses yet.", contentAction: "Manage courses and lessons", billingNote: "Billing and subscriptions are not available yet.", settingsNote: "Platform settings are not available yet.", role: "Role", assigned: "students" },
};

function AdminDashboard() {
  const [language, setLanguage] = useState("ar");
  const [dashboard, setDashboard] = useState(null);
  const [users, setUsers] = useState([]);
  const [courses, setCourses] = useState([]);
  const [classOverview, setClassOverview] = useState({ classes: [], total: 0, upcoming: 0, past: 0, cancelled: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const text = translations[language];

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const responses = await Promise.all([authFetch("/api/admin/dashboard"), authFetch("/api/admin/users"), authFetch("/api/admin/courses"), authFetch("/api/admin/classes")]);
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failedIndex = responses.findIndex((response) => !response.ok);
      if (failedIndex >= 0) throw new Error(payloads[failedIndex].detail || "Unable to load administrator data");
      setDashboard(payloads[0]);
      setUsers(payloads[1].users || []);
      setCourses(payloads[2].courses || []);
      setClassOverview(payloads[3]);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) return <StaffState message={language === "ar" ? "جارٍ تحميل لوحة الإدارة..." : "Loading administrator dashboard..."} />;
  if (error) return <StaffState error={error} message={error} onRetry={loadData} />;

  const administrator = dashboard.currentUser;

  return <div className="staff-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <StaffNavigation role="administrator" language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="staff-main">
      <header className="staff-header"><div><p className="staff-eyebrow">FLUENT PATH / ADMINISTRATION</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><div className="staff-account"><span>{administrator.fullName.charAt(0).toUpperCase()}</span><div><strong>{administrator.fullName}</strong><small>{administrator.email}</small></div></div></header>
      <section className="staff-hero"><div><span className="staff-eyebrow" style={{ color: "var(--fp-accent-border)" }}>{text.welcome}</span><h2>{text.overview}</h2><p>{language === "ar" ? "المؤشرات أدناه مبنية على البيانات المحفوظة." : "The indicators below are built from persisted platform data."}</p></div><div className="staff-hero-badge">A</div></section>
      <section className="staff-stats"><StaffStat icon="♙" label={text.students} value={dashboard.totalStudents} detail={text.users} /><StaffStat icon="T" label={text.teachers} value={dashboard.totalTeachers} detail={text.users} /><StaffStat icon="◈" label={text.courses} value={dashboard.totalCourses} detail={text.courses} /><StaffStat icon="✓" label={text.activity} value={dashboard.totalCompletedLessons} detail={text.lessons} /></section>
      <div className="staff-grid"><section className="staff-panel" id="users"><div className="staff-panel-heading"><div><span>01 / USERS</span><h2>{text.recent}</h2></div><small>{users.length}</small></div><div className="admin-user-list">{users.length ? users.map((user) => <div className="admin-user" key={user.id}><div><strong>{user.fullName}</strong><small>{user.email}</small></div><span className="role-pill">{user.role}</span></div>) : <p className="staff-empty">{text.noUsers}</p>}</div></section><section className="staff-panel" id="analytics"><div className="staff-panel-heading"><div><span>02 / ANALYTICS</span><h2>{language === "ar" ? "ملخص المنصة" : "Platform summary"}</h2></div></div><div className="course-mini-list"><div className="course-mini"><strong>{text.students}</strong><small>{dashboard.totalStudents} {text.users}</small></div><div className="course-mini"><strong>{text.teachers}</strong><small>{dashboard.totalTeachers} {text.users}</small></div><div className="course-mini"><strong>{text.homework}</strong><small>{dashboard.totalHomework}</small></div></div></section></div>
      <section className="staff-panel" id="courses"><div className="staff-panel-heading"><div><span>03 / CATALOG</span><h2>{text.courseManagement}</h2></div><small>{courses.length}</small></div><div className="staff-catalog-grid">{courses.length ? courses.map((course) => <div className="staff-catalog-card" key={course.id}><strong>{language === "ar" ? course.titleAr : course.title}</strong><small>{course.level} · {course.lessons.length} {text.lessons}</small></div>) : <p className="staff-empty">{text.noCourses}</p>}</div></section>
      <section className="staff-panel" id="classes"><div className="staff-panel-heading"><div><span>04 / SCHEDULE</span><h2>{text.classes}</h2></div><small>{classOverview.total}</small></div><div className="class-admin-overview"><div className="class-admin-stat"><small>{text.upcoming}</small><strong>{classOverview.upcoming}</strong></div><div className="class-admin-stat"><small>{text.past}</small><strong>{classOverview.past}</strong></div><div className="class-admin-stat"><small>{text.cancelled}</small><strong>{classOverview.cancelled}</strong></div></div><div className="admin-class-list">{classOverview.classes.length ? classOverview.classes.map((item) => <article className="admin-class-row" key={item.id}><div><strong>{item.title}</strong><small>{item.teacher?.fullName || "—"} · {item.course?.title || item.level || "—"} · {(item.students || []).length} {text.assigned}</small><small>{formatClassDate(item, language)}</small></div><ClassStatus classItem={item} language={language} /></article>) : <p className="staff-empty">{text.noClasses}</p>}</div></section>
      <div className="staff-grid"><section className="staff-panel" id="content"><div className="staff-panel-heading"><div><span>05 / CONTENT</span><h2>{text.courseManagement}</h2></div></div><Link className="admin-content-link" to="/admin-content">{text.contentAction} ↗</Link></section><section id="billing"><MvpNotice>{text.billingNote}</MvpNotice></section><section id="settings"><MvpNotice>{text.settingsNote}</MvpNotice></section></div>
    </main>
  </div>;
}

export default AdminDashboard;
