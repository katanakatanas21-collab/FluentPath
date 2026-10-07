import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../auth";
import { MessageBubble, SocialNavigation, SocialState, ConversationList } from "./SocialComponents";
import "./Social.css";

const copy = {
  ar: { title: "الرسائل", subtitle: "محادثاتك مع المعلمين والطلاب المرتبطين بحصصك.", loading: "جارٍ تحميل الرسائل...", empty: "لا توجد محادثات بعد.", choose: "اختر محادثة أو ابدأ واحدة من جهات الاتصال المتاحة.", contacts: "جهات الاتصال المرتبطة", start: "بدء محادثة", send: "إرسال", sending: "جارٍ الإرسال...", placeholder: "اكتب رسالتك...", failed: "تعذر تحميل الرسائل.", unread: "غير مقروءة", adminScope: "محادثات الإدارة مع المعلمين فقط." },
  en: { title: "Messages", subtitle: "Conversations with teachers and students connected to your classes.", loading: "Loading messages...", empty: "No conversations yet.", choose: "Select a conversation or start one from your available contacts.", contacts: "Related contacts", start: "Start conversation", send: "Send", sending: "Sending...", placeholder: "Write a message...", failed: "Could not load messages.", unread: "unread", adminScope: "Administrator conversations are limited to teacher staff." },
};

function MessagesPage({ role = "student" }) {
  const [language, setLanguage] = useState("ar");
  const [contacts, setContacts] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [thread, setThread] = useState([]);
  const [message, setMessage] = useState("");
  const [selectedContact, setSelectedContact] = useState("");
  const [loading, setLoading] = useState(true);
  const [threadLoading, setThreadLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const text = copy[language];

  const loadLists = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const responses = await Promise.all([authFetch("/api/messaging/contacts"), authFetch("/api/conversations")]);
      const payloads = await Promise.all(responses.map((response) => response.json()));
      const failed = responses.findIndex((response) => !response.ok);
      if (failed >= 0) throw new Error(payloads[failed].detail || text.failed);
      setContacts(payloads[0].contacts || []);
      setConversations(payloads[1].conversations || []);
      if (selectedId && !(payloads[1].conversations || []).some((conversation) => conversation.id === selectedId)) setSelectedId("");
    } catch (loadError) { setError(loadError.message); }
    finally { setLoading(false); }
  }, [selectedId, text.failed]);

  const loadThread = useCallback(async (conversationId) => {
    if (!conversationId) return;
    setThreadLoading(true); setError("");
    try {
      const response = await authFetch(`/api/conversations/${conversationId}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setThread(payload.messages || []);
      setSelectedId(conversationId);
      await loadLists();
    } catch (loadError) { setError(loadError.message); }
    finally { setThreadLoading(false); }
  }, [loadLists, text.failed]);

  useEffect(() => { loadLists(); }, [loadLists]);
  useEffect(() => { if (selectedId) loadThread(selectedId); }, [selectedId, loadThread]);

  const startConversation = async (event) => {
    event.preventDefault();
    const contact = contacts[Number(selectedContact)];
    if (!contact) return;
    setError("");
    try {
      const body = role === "student" ? { classId: contact.classId } : role === "teacher" ? { classId: contact.classId, studentId: contact.user.id } : { staffUserId: contact.user.id };
      const response = await authFetch("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      await loadLists();
      setSelectedId(payload.conversation.id);
    } catch (startError) { setError(startError.message); }
  };

  const sendMessage = async (event) => {
    event.preventDefault();
    if (!message.trim() || !selectedId) return;
    setSending(true); setError("");
    try {
      const response = await authFetch(`/api/conversations/${selectedId}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: message }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.failed);
      setThread((current) => [...current, payload.message]);
      setMessage("");
      await loadLists();
    } catch (sendError) { setError(sendError.message); }
    finally { setSending(false); }
  };

  return <div className={role === "student" ? "homework-layout" : "staff-shell"} dir={language === "ar" ? "rtl" : "ltr"}>
    <SocialNavigation role={role} language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className={role === "student" ? "homework-main" : "staff-main"}>
      <header className={role === "student" ? "homework-page-header" : "staff-header"}><div><p className={role === "student" ? "homework-eyebrow" : "staff-eyebrow"}>FLUENT PATH / MESSAGES</p><h1>{text.title}</h1><p>{text.subtitle}</p></div></header>
      {error && <p className="social-error" role="alert">{error}</p>}
      {role === "administrator" && <p className="social-scope-note">{text.adminScope}</p>}
      {loading ? <SocialState language={language}>{text.loading}</SocialState> : <div className="messaging-layout"><aside className="messaging-rail"><form className="start-conversation-form" onSubmit={startConversation}><label htmlFor="message-contact">{text.contacts}</label><select id="message-contact" value={selectedContact} onChange={(event) => setSelectedContact(event.target.value)} required><option value="">{text.contacts}</option>{contacts.map((contact, index) => <option key={`${contact.user.id}-${contact.classId || "staff"}`} value={index}>{contact.user.fullName}{contact.classTitle ? ` · ${contact.classTitle}` : ""}</option>)}</select><button type="submit" disabled={!contacts.length}>{text.start}</button></form><ConversationList conversations={conversations} selectedId={selectedId} language={language} onSelect={setSelectedId} /></aside><section className="message-thread">{selectedId ? <>{threadLoading ? <SocialState language={language}>{text.loading}</SocialState> : <><div className="message-list">{thread.map((item) => <MessageBubble key={item.id} message={item} />)}</div><form className="message-compose" onSubmit={sendMessage}><textarea aria-label={text.placeholder} placeholder={text.placeholder} value={message} onChange={(event) => setMessage(event.target.value)} rows="2" required maxLength="8000" /><button type="submit" disabled={sending}>{sending ? text.sending : text.send}</button></form></>}</> : <SocialState language={language}>{text.choose}</SocialState>}</section></div>}
    </main>
  </div>;
}

export default MessagesPage;
