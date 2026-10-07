import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../auth";
import { PostCard, ReplyItem, SocialNavigation, SocialState } from "./SocialComponents";
import "./Social.css";

const copy = {
  ar: { title: "المجتمع", subtitle: "شارك أسئلتك وأفكارك مع مجتمع Fluent Path.", general: "عام", course: "دورة", class: "حصة", selectArea: "اختر مساحة النقاش", titleLabel: "عنوان المنشور", content: "اكتب منشورك", publish: "نشر", publishing: "جارٍ النشر...", search: "ابحث في النقاشات", posts: "النقاشات", empty: "لا توجد منشورات في هذه المساحة بعد.", loading: "جارٍ تحميل المجتمع...", reply: "اكتب ردًا", sendReply: "إرسال الرد", report: "سبب الإبلاغ", sendReport: "إرسال البلاغ", reportSent: "تم إرسال البلاغ للمراجعة.", saving: "جارٍ الحفظ...", cancel: "إلغاء", editTitle: "تعديل المنشور", save: "حفظ التعديل", deleteConfirm: "هل تريد حذف هذا المنشور؟", failed: "تعذر تحميل المجتمع.", reports: "البلاغات", postsView: "المنشورات", hide: "إخفاء", restore: "إعادة الإظهار", dismiss: "إغلاق البلاغ", noReports: "لا توجد بلاغات مفتوحة.", openReports: "بلاغات مفتوحة", reportReasonRequired: "سبب الإبلاغ مطلوب.", viewReplies: "عرض الردود", generalArea: "النقاش العام", noAreas: "لا توجد مساحات متاحة." },
  en: { title: "Community", subtitle: "Share questions and ideas with the Fluent Path community.", general: "General", course: "Course", class: "Class", selectArea: "Choose a discussion area", titleLabel: "Post title", content: "Write your post", publish: "Publish", publishing: "Publishing...", search: "Search discussions", posts: "Discussions", empty: "No posts in this area yet.", loading: "Loading community...", reply: "Write a reply", sendReply: "Send reply", report: "Report reason", sendReport: "Submit report", reportSent: "Report sent for review.", saving: "Saving...", cancel: "Cancel", editTitle: "Edit post", save: "Save changes", deleteConfirm: "Delete this post?", failed: "Could not load community.", reports: "Reports", postsView: "Posts", hide: "Hide", restore: "Restore", dismiss: "Dismiss report", noReports: "No open reports.", openReports: "Open reports", reportReasonRequired: "A report reason is required.", viewReplies: "View replies", generalArea: "General discussion", noAreas: "No discussion areas available." },
};

function CommunityPage({ role = "student", initialView = "posts" }) {
  const [language, setLanguage] = useState("ar");
  const [user, setUser] = useState(null);
  const [areas, setAreas] = useState({ courses: [], classes: [] });
  const [posts, setPosts] = useState([]);
  const [reports, setReports] = useState([]);
  const [view, setView] = useState(initialView);
  const [area, setArea] = useState("general");
  const [areaId, setAreaId] = useState("");
  const [search, setSearch] = useState("");
  const [form, setForm] = useState({ title: "", content: "" });
  const [replyContent, setReplyContent] = useState({});
  const [details, setDetails] = useState({});
  const [editingPost, setEditingPost] = useState(null);
  const [reportingPost, setReportingPost] = useState("");
  const [reportReason, setReportReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const text = copy[language];
  const isAdmin = role === "administrator";

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const responses = await Promise.all([authFetch("/api/me"), authFetch("/api/community/areas")]);
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failed = responses.findIndex((response) => !response.ok);
      if (failed >= 0) throw new Error(payloads[failed].detail || text.failed);
      setUser(payloads[0]);
      setAreas(payloads[1].areas || { courses: [], classes: [] });
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [text.failed]);

  const loadPosts = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (area !== "all") params.set("scope", area);
      if (area === "course" && areaId) params.set("courseId", areaId);
      if (area === "class" && areaId) params.set("classId", areaId);
      if (search.trim()) params.set("search", search.trim());
      const response = await authFetch(`/api/community/posts?${params.toString()}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setPosts(payload.posts || []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [area, areaId, search, text.failed]);

  const loadReports = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/admin/community/reports");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setReports((payload.reports || []).filter((report) => report.status === "open"));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [text.failed]);

  useEffect(() => { loadBase(); }, [loadBase]);
  useEffect(() => { if (!isAdmin || view === "posts") loadPosts(); }, [isAdmin, loadPosts, view]);
  useEffect(() => { if (isAdmin && view === "reports") loadReports(); }, [isAdmin, loadReports, view]);

  const submitPost = async (event) => {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await authFetch("/api/community/posts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: form.title, content: form.content, scope: area === "all" ? "general" : area, courseId: area === "course" ? areaId : null, classId: area === "class" ? areaId : null }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setForm({ title: "", content: "" });
      setNotice(text.publish);
      await loadPosts();
    } catch (submitError) { setError(submitError.message); }
    finally { setSaving(false); }
  };

  const toggleDetails = async (postId) => {
    if (details[postId]) { setDetails((current) => ({ ...current, [postId]: null })); return; }
    try {
      const response = await authFetch(`/api/community/posts/${postId}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setDetails((current) => ({ ...current, [postId]: payload }));
    } catch (detailError) { setError(detailError.message); }
  };

  const sendReply = async (event, postId) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const response = await authFetch(`/api/community/posts/${postId}/replies`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: replyContent[postId] || "" }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setReplyContent((current) => ({ ...current, [postId]: "" }));
      const detailResponse = await authFetch(`/api/community/posts/${postId}`);
      const detailPayload = await detailResponse.json();
      if (!detailResponse.ok) throw new Error(detailPayload.detail || text.failed);
      setDetails((current) => ({ ...current, [postId]: detailPayload }));
      await loadPosts();
    } catch (replyError) { setError(replyError.message); }
    finally { setSaving(false); }
  };

  const editPost = async (event, postId) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const response = await authFetch(`/api/community/posts/${postId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(editingPost) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setEditingPost(null); await loadPosts();
    } catch (editError) { setError(editError.message); }
    finally { setSaving(false); }
  };

  const removePost = async (postId) => {
    if (!window.confirm(text.deleteConfirm)) return;
    const response = await authFetch(`/api/community/posts/${postId}`, { method: "DELETE" });
    if (!response.ok) { const payload = await response.json(); setError(payload.detail || text.failed); return; }
    await loadPosts();
  };

  const likePost = async (postId) => {
    const response = await authFetch(`/api/community/posts/${postId}/like`, { method: "POST" });
    if (!response.ok) { const payload = await response.json(); setError(payload.detail || text.failed); return; }
    await loadPosts();
  };

  const sendReport = async (event, postId) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const response = await authFetch(`/api/community/posts/${postId}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reportReason }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setReportingPost(""); setReportReason(""); setNotice(text.reportSent);
    } catch (reportError) { setError(reportError.message); }
    finally { setSaving(false); }
  };

  const moderatePost = async (post) => {
    const response = await authFetch(`/api/community/posts/${post.id}/moderate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: post.status === "hidden" ? "restore" : "hide" }) });
    if (!response.ok) { const payload = await response.json(); setError(payload.detail || text.failed); return; }
    await loadPosts();
  };

  const resolveReport = async (report, action) => {
    const response = await authFetch(`/api/admin/community/reports/${report.id}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    if (!response.ok) { const payload = await response.json(); setError(payload.detail || text.failed); return; }
    await loadReports();
  };

  const areaOptions = area === "course" ? areas.courses : area === "class" ? areas.classes : [];

  return <div className={role === "student" ? "homework-layout" : "staff-shell"} dir={language === "ar" ? "rtl" : "ltr"}>
    <SocialNavigation role={role} language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className={role === "student" ? "homework-main" : "staff-main"}>
      <header className={role === "student" ? "homework-page-header" : "staff-header"}><div><p className={role === "student" ? "homework-eyebrow" : "staff-eyebrow"}>FLUENT PATH / COMMUNITY</p><h1>{isAdmin ? (language === "ar" ? "إدارة المجتمع" : "Community management") : text.title}</h1><p>{text.subtitle}</p></div></header>
      {isAdmin && <div className="social-switch"><button type="button" className={view === "posts" ? "active" : ""} onClick={() => setView("posts")}>{text.postsView}</button><button type="button" className={view === "reports" ? "active" : ""} onClick={() => setView("reports")}>{text.reports}<span>{reports.length}</span></button></div>}
      {error && <p role="alert" className="social-error">{error}</p>}{notice && <p role="status" className="social-notice">{notice}</p>}
      {loading ? <SocialState language={language}>{text.loading}</SocialState> : view === "reports" && isAdmin ? reports.length ? <div className="social-post-list">{reports.map((report) => <article className="social-report" key={report.id}><div className="social-post-meta"><strong>{report.reporter?.fullName || "—"}</strong><time>{report.createdAt ? new Date(report.createdAt).toLocaleString(language === "ar" ? "ar" : "en") : ""}</time></div><p>{report.reason}</p>{report.post && <div className="social-reported-post"><strong>{report.post.title}</strong><p>{report.post.content}</p><small>{report.post.author?.fullName || "—"}</small></div>}<div className="social-post-actions"><button type="button" onClick={() => resolveReport(report, "hide")}>{text.hide}</button><button type="button" onClick={() => resolveReport(report, "dismiss")}>{text.dismiss}</button></div></article>)}</div> : <SocialState language={language}>{text.noReports}</SocialState> : <>
        {!isAdmin && <form className="social-compose" onSubmit={submitPost}><h2>{language === "ar" ? "منشور جديد" : "New post"}</h2><div className="social-compose-row"><label htmlFor="community-scope">{text.selectArea}</label><select id="community-scope" value={area} onChange={(event) => { setArea(event.target.value); setAreaId(""); }}><option value="general">{text.general}</option><option value="course">{text.course}</option><option value="class">{text.class}</option></select></div>{area !== "general" && <select aria-label={text.selectArea} value={areaId} onChange={(event) => setAreaId(event.target.value)} required><option value="">{text.selectArea}</option>{areaOptions.map((option) => <option key={option.id} value={option.id}>{option.title || option.titleAr || option.classTitle}</option>)}</select>}<label htmlFor="community-title">{text.titleLabel}</label><input id="community-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required maxLength="180" /><label htmlFor="community-content">{text.content}</label><textarea id="community-content" rows="3" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} required maxLength="8000" /><button type="submit" disabled={saving}>{saving ? text.publishing : text.publish}</button></form>}
        <section className="social-feed"><div className="social-feed-heading"><h2>{text.posts}</h2><input aria-label={text.search} placeholder={text.search} value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") loadPosts(); }} /><button type="button" onClick={loadPosts}>{text.search}</button></div>{posts.length ? <div className="social-post-list">{posts.map((post) => <div key={post.id}><PostCard post={post} language={language} userId={user?.id} onOpen={() => toggleDetails(post.id)} onLike={() => likePost(post.id)} onEdit={() => setEditingPost({ id: post.id, title: post.title, content: post.content })} onDelete={() => removePost(post.id)} onReport={() => setReportingPost(reportingPost === post.id ? "" : post.id)} onModerate={role === "teacher" || isAdmin ? () => moderatePost(post) : null} />{editingPost?.id === post.id && <form className="social-inline-form" onSubmit={(event) => editPost(event, post.id)}><input value={editingPost.title} onChange={(event) => setEditingPost({ ...editingPost, title: event.target.value })} required /><textarea value={editingPost.content} onChange={(event) => setEditingPost({ ...editingPost, content: event.target.value })} required /><button type="submit" disabled={saving}>{text.save}</button><button type="button" onClick={() => setEditingPost(null)}>{text.cancel}</button></form>}{reportingPost === post.id && <form className="social-inline-form" onSubmit={(event) => sendReport(event, post.id)}><label>{text.report}</label><textarea value={reportReason} onChange={(event) => setReportReason(event.target.value)} required maxLength="1000" /><button type="submit" disabled={saving}>{text.sendReport}</button></form>}{details[post.id] && <section className="social-replies"><h3>{text.viewReplies}</h3>{details[post.id].replies.map((reply) => <ReplyItem key={reply.id} reply={reply} language={language} userId={user?.id} onEdit={() => { const value = window.prompt(language === "ar" ? "تعديل الرد" : "Edit reply", reply.content); if (value) authFetch(`/api/community/replies/${reply.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: value }) }).then(toggleDetails(post.id)); }} onDelete={() => authFetch(`/api/community/replies/${reply.id}`, { method: "DELETE" }).then(toggleDetails(post.id))} onModerate={role === "teacher" || isAdmin ? () => authFetch(`/api/community/replies/${reply.id}`, { method: "DELETE" }).then(toggleDetails(post.id)) : null} />)}<form className="social-inline-form" onSubmit={(event) => sendReply(event, post.id)}><textarea aria-label={text.reply} placeholder={text.reply} value={replyContent[post.id] || ""} onChange={(event) => setReplyContent({ ...replyContent, [post.id]: event.target.value })} required /><button type="submit" disabled={saving}>{text.sendReply}</button></form></section>}</div>)}</div> : <SocialState language={language}>{text.empty}</SocialState>}</section>
      </>}
    </main>
  </div>;
}

export default CommunityPage;
