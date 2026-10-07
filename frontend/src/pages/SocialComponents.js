import StaffNavigation from "./StaffNavigation";
import { HomeworkNavigation } from "./HomeworkComponents";
import "./Social.css";

export function SocialNavigation({ role, language, onLanguageChange }) {
  if (role === "teacher" || role === "administrator") {
    return <StaffNavigation role={role} language={language} onLanguageChange={onLanguageChange} />;
  }
  return <HomeworkNavigation language={language} onLanguageChange={onLanguageChange} active="community" />;
}

export function SocialState({ language, loading, error, onRetry, children }) {
  return <div className="social-state" role={error ? "alert" : undefined}><span>{error ? "!" : "F"}</span><p>{error || children || (language === "ar" ? "جارٍ التحميل..." : "Loading...")}</p>{error && onRetry && <button type="button" onClick={onRetry}>{language === "ar" ? "إعادة المحاولة" : "Try again"}</button>}</div>;
}

export function PostCard({ post, language, userId, onOpen, onLike, onEdit, onDelete, onReport, onModerate }) {
  const labels = language === "ar"
    ? { reply: "رد", like: "إعجاب", unlike: "إلغاء الإعجاب", edit: "تعديل", delete: "حذف", report: "إبلاغ", hide: "إخفاء", restore: "إظهار", general: "نقاش عام", course: "نقاش دورة", class: "نقاش حصة" }
    : { reply: "Replies", like: "Like", unlike: "Unlike", edit: "Edit", delete: "Delete", report: "Report", hide: "Hide", restore: "Restore", general: "General", course: "Course", class: "Class" };
  const own = post.author?.id === userId;
  const area = post.scope === "course" ? `${labels.course}${post.courseId ? ` · ${post.courseId}` : ""}` : post.scope === "class" ? labels.class : labels.general;
  return <article className={`social-post ${post.status === "hidden" ? "is-hidden" : ""}`}>
    <div className="social-post-meta"><span>{post.author?.fullName || "—"}<em>{post.author?.role}</em></span><time>{post.createdAt ? new Date(post.createdAt).toLocaleString(language === "ar" ? "ar" : "en") : ""}</time></div>
    <small className="social-post-area">{area}{post.status === "hidden" ? ` · ${language === "ar" ? "مخفي" : "Hidden"}` : ""}</small>
    <h2>{post.title}</h2><p className="social-post-content">{post.content}</p>
    <div className="social-post-actions"><button type="button" onClick={onOpen}>{labels.reply} · {post.replyCount}</button><button type="button" onClick={onLike}>{post.likedByMe ? labels.unlike : labels.like} · {post.likeCount}</button>{own && <><button type="button" onClick={onEdit}>{labels.edit}</button><button type="button" onClick={onDelete}>{labels.delete}</button></>}{!own && userId && post.author?.role !== "administrator" && <button type="button" onClick={onReport}>{labels.report}</button>}{onModerate && <button type="button" onClick={onModerate}>{post.status === "hidden" ? labels.restore : labels.hide}</button>}</div>
  </article>;
}

export function ReplyItem({ reply, language, userId, onEdit, onDelete, onModerate }) {
  const own = reply.author?.id === userId;
  return <article className="social-reply"><div className="social-post-meta"><span>{reply.author?.fullName || "—"}<em>{reply.author?.role}</em></span><time>{reply.createdAt ? new Date(reply.createdAt).toLocaleString(language === "ar" ? "ar" : "en") : ""}</time></div><p>{reply.content}</p><div className="social-post-actions">{own && <button type="button" onClick={onEdit}>{language === "ar" ? "تعديل" : "Edit"}</button>}{(own || onModerate) && <button type="button" onClick={onDelete}>{language === "ar" ? "حذف" : "Delete"}</button>}{onModerate && <button type="button" onClick={onModerate}>{language === "ar" ? "إشراف" : "Moderate"}</button>}</div></article>;
}

export function ConversationList({ conversations, selectedId, language, onSelect }) {
  if (!conversations.length) return <p className="social-empty-inline">{language === "ar" ? "لا توجد محادثات بعد." : "No conversations yet."}</p>;
  return <div className="conversation-list">{conversations.map((conversation) => <button className={`conversation-list-item ${selectedId === conversation.id ? "active" : ""}`} type="button" key={conversation.id} onClick={() => onSelect(conversation.id)}><span className="conversation-avatar">{conversation.participants?.[0]?.fullName?.charAt(0) || "F"}</span><span className="conversation-list-copy"><strong>{conversation.participants?.map((person) => person.fullName).join(", ") || (language === "ar" ? "محادثة" : "Conversation")}</strong><small>{conversation.lastMessage || (language === "ar" ? "ابدأ المحادثة" : "Start the conversation")}</small></span>{conversation.unreadCount > 0 && <span className="unread-badge">{conversation.unreadCount}</span>}</button>)}</div>;
}

export function MessageBubble({ message }) {
  return <article className={`message-bubble ${message.mine ? "mine" : ""}`}><p>{message.content}</p><small>{message.createdAt ? new Date(message.createdAt).toLocaleString() : ""}{message.mine && message.readByOthers ? " · ✓✓" : ""}</small></article>;
}
