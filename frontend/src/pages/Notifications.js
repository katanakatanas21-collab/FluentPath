import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { authFetch } from "../auth";
import StaffNavigation from "./StaffNavigation";
import { HomeworkNavigation } from "./HomeworkComponents";
import "./Notifications.css";

const copy = {
  en: { title: "Notifications", all: "Mark all as read", loading: "Loading notifications…", empty: "You’re all caught up.", error: "Could not load notifications.", retry: "Try again", read: "Mark as read", unread: "unread", dashboard: "Dashboard" },
  ar: { title: "الإشعارات", all: "تحديد الكل كمقروء", loading: "جارٍ تحميل الإشعارات…", empty: "لا توجد إشعارات جديدة.", error: "تعذر تحميل الإشعارات.", retry: "إعادة المحاولة", read: "تحديد كمقروء", unread: "غير مقروء", dashboard: "لوحة التحكم" },
};

const links = { homework_assigned: "/homework", homework_graded: "/homework", homework_submitted: "/teacher-homework", new_message: "/messages", community_reply: "/community", community_activity: "/community", achievement_unlocked: "/achievements", level_up: "/achievements", streak_milestone: "/achievements", class_cancelled: "/schedule", upcoming_class_reminder: "/schedule", course_progress_milestone: "/courses", lesson_completed: "/teacher-dashboard", student_achievement: "/teacher-dashboard", new_user_registration: "/admin-dashboard", community_report: "/admin-community/reports" };

export function NotificationItem({ item, language, onRead }) {
  const ar = language === "ar";
  const path = links[item.type];
  const text = item.message;
  return <article className={`notification-item ${item.read ? "" : "notification-unread"}`}>
    {path ? <Link to={path} className="notification-copy" onClick={() => !item.read && onRead(item.id)}><strong>{item.title}</strong><span>{text}</span><time>{new Date(item.created_at).toLocaleString(ar ? "ar" : "en")}</time></Link> : <div className="notification-copy"><strong>{item.title}</strong><span>{text}</span><time>{new Date(item.created_at).toLocaleString(ar ? "ar" : "en")}</time></div>}
    {!item.read && <button type="button" onClick={() => onRead(item.id)}>{ar ? "مقروء" : "Mark read"}</button>}
  </article>;
}

export function NotificationList({ notifications, language, onRead, onReadAll, compact = false }) {
  const text = copy[language];
  return <section className={`notification-list ${compact ? "notification-compact" : ""}`}>
    <header><h2>{text.title}</h2>{notifications.some((item) => !item.read) && <button type="button" onClick={onReadAll}>{text.all}</button>}</header>
    {notifications.length ? notifications.map((item) => <NotificationItem key={item.id} item={item} language={language} onRead={onRead} />) : <p className="notification-empty">{text.empty}</p>}
  </section>;
}

export function NotificationBell({ language = "en" }) {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const navigate = useNavigate();
  const refreshCount = useCallback(async () => {
    try { const response = await authFetch("/api/me/notifications/unread-count"); if (response.ok) setCount((await response.json()).unreadCount || 0); } catch { /* next page view can refresh */ }
  }, []);
  const loadItems = useCallback(async () => {
    try { const response = await authFetch("/api/me/notifications"); if (response.ok) setItems((await response.json()).notifications || []); } catch { /* list page exposes retry */ }
  }, []);
  useEffect(() => { refreshCount(); }, [refreshCount]);
  const markRead = async (id) => { await authFetch(`/api/me/notifications/${id}/read`, { method: "PATCH" }); await Promise.all([loadItems(), refreshCount()]); };
  const markAll = async () => { await authFetch("/api/me/notifications/read-all", { method: "POST" }); await Promise.all([loadItems(), refreshCount()]); };
  return <div className="notification-bell-wrap">
    <button className="notification-bell" type="button" aria-label={language === "ar" ? "الإشعارات" : "Notifications"} aria-expanded={open} onClick={() => { const next = !open; setOpen(next); if (next) loadItems(); }}>♧{count > 0 && <span>{count > 99 ? "99+" : count}</span>}</button>
    {open && <div className="notification-popover"><NotificationList notifications={items.slice(0, 5)} language={language} onRead={markRead} onReadAll={markAll} compact /><button type="button" className="notification-view-all" onClick={() => navigate("/notifications")}>{language === "ar" ? "عرض كل الإشعارات" : "View all notifications"}</button></div>}
  </div>;
}

export default function NotificationsPage() {
  const [language, setLanguage] = useState("ar");
  const [role, setRole] = useState("student");
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const text = copy[language];
  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try { const [list, user] = await Promise.all([authFetch("/api/me/notifications"), authFetch("/api/me")]); if (!list.ok || !user.ok) throw new Error(); setNotifications((await list.json()).notifications || []); setRole((await user.json()).role); }
    catch { setError(true); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const markRead = async (id) => { await authFetch(`/api/me/notifications/${id}/read`, { method: "PATCH" }); await load(); };
  const markAll = async () => { await authFetch("/api/me/notifications/read-all", { method: "POST" }); await load(); };
  const onLanguageChange = () => setLanguage((value) => value === "ar" ? "en" : "ar");
  return <div className="notification-page" dir={language === "ar" ? "rtl" : "ltr"}>
    {role === "student" ? <HomeworkNavigation language={language} onLanguageChange={onLanguageChange} active="notifications" /> : <StaffNavigation role={role} language={language} onLanguageChange={onLanguageChange} />}
    <main className="notification-main"><div className="notification-page-heading"><Link to={role === "student" ? "/student-dashboard" : role === "teacher" ? "/teacher-dashboard" : "/admin-dashboard"}>← {text.dashboard}</Link><h1>{text.title}</h1></div>
      {loading ? <p>{text.loading}</p> : error ? <div role="alert"><p>{text.error}</p><button type="button" onClick={load}>{text.retry}</button></div> : <NotificationList notifications={notifications} language={language} onRead={markRead} onReadAll={markAll} />}
    </main>
  </div>;
}
