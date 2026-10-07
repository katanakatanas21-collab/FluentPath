import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import CourseNavigation from "./CourseNavigation";
import { authFetch } from "../auth";
import "./AiTeacher.css";

const modes = ["conversation", "grammar", "vocabulary", "writing", "speaking"];
const copy = {
  ar: {
    title: "معلم الذكاء الاصطناعي", subtitle: "تدريب إنجليزي شخصي يتكيف مع مستواك.", select: "اختر طريقة التدريب", start: "ابدأ التدريب", history: "جلساتك الأخيرة", noHistory: "ستظهر جلسات التدريب هنا.", loading: "جارٍ تحميل جلساتك…", loadingSession: "جارٍ فتح الجلسة…", emptyTitle: "ابدأ جلسة تدريب جديدة", emptyBody: "اختر طريقة التدريب التي تناسب هدفك اليوم.", send: "إرسال", placeholder: "اكتب إجابتك بالإنجليزية…", sending: "جارٍ التقييم…", prompt: "اكتب إجابتك هنا. التقييم مخصص للتدريب فقط ولا يمنح شهادة CEFR رسمية.", score: "تقييم التدريب", feedback: "ملاحظات", corrections: "تصحيحات مقترحة", next: "الخطوة التالية", grammar_feedback: "القواعد", vocabulary_feedback: "المفردات", clarity_feedback: "الوضوح", relevance_feedback: "الارتباط بالموضوع", xp: "XP مكتسبة", config: "خدمة معلم الذكاء الاصطناعي غير مهيأة بعد. اطلب من مسؤول المنصة إضافة OPENAI_API_KEY إلى إعدادات الخادم.", rate: "وصلت إلى الحد المؤقت للتدريب. حاول مرة أخرى لاحقًا.", unavailable: "تعذر الوصول إلى المعلم الآن. حاول مرة أخرى.", error: "تعذر إكمال الطلب.", speakingNote: "التدريب الصوتي غير متاح بعد؛ استخدم الإجابات النصية فقط.", conversation: "محادثة", grammar: "القواعد", vocabulary: "المفردات", writing: "الكتابة", speaking: "التحضير للمحادثة", conversationDesc: "تحدث بالكتابة مع شريك محادثة يسأل سؤالًا واحدًا في كل مرة.", grammarDesc: "تدرب على قاعدة مناسبة لمستواك مع تصحيح مبسط.", vocabularyDesc: "راجع الكلمات واستخدمها في إجابات قصيرة.", writingDesc: "اكتب فقرة قصيرة واحصل على ملاحظات عملية.", speakingDesc: "تدرب على إجابات مقابلة أو محادثة عبر النص.", level: "المستوى عند بدء الجلسة", completed: "اكتملت الجلسة", active: "جلسة جارية", newSession: "جلسة جديدة", back: "اختيار طريقة أخرى", assistant: "معلم Fluent Path", learner: "أنت", modeLabel: "طريقة التدريب", noLevel: "غير محدد", certification: "هذا تقييم تدريبي فقط وليس شهادة أو تحديدًا رسميًا لمستوى CEFR.", retry: "إعادة المحاولة", dashboard: "لوحة الطالب",
  },
  en: {
    title: "AI Teacher", subtitle: "Personal English practice adapted to your level.", select: "Choose a practice mode", start: "Start practice", history: "Recent sessions", noHistory: "Your practice sessions will appear here.", loading: "Loading your sessions…", loadingSession: "Opening session…", emptyTitle: "Start a new practice session", emptyBody: "Choose the kind of practice that fits your goal today.", send: "Send response", placeholder: "Write your answer in English…", sending: "Reviewing…", prompt: "Write your response here. Feedback is for practice only and is not an official CEFR certificate.", score: "Practice score", feedback: "Feedback", corrections: "Suggested corrections", next: "Next step", grammar_feedback: "Grammar", vocabulary_feedback: "Vocabulary", clarity_feedback: "Clarity", relevance_feedback: "Relevance", xp: "XP earned", config: "AI Teacher is not configured yet. Ask your platform administrator to add OPENAI_API_KEY to the backend environment.", rate: "You have reached the temporary practice limit. Please try again later.", unavailable: "The AI Teacher is unavailable right now. Please try again.", error: "The request could not be completed.", speakingNote: "Voice practice is not available yet. Text responses only.", conversation: "Conversation", grammar: "Grammar", vocabulary: "Vocabulary", writing: "Writing", speaking: "Speaking preparation", conversationDesc: "Practice with a conversation partner who asks one question at a time.", grammarDesc: "Try a level-appropriate task with a simple correction.", vocabularyDesc: "Review useful words and use them in short answers.", writingDesc: "Write a short response and get practical feedback.", speakingDesc: "Prepare spoken answers using text prompts and responses.", level: "Level when session started", noLevel: "Not set", completed: "Session completed", active: "In progress", newSession: "New session", back: "Choose another mode", assistant: "Fluent Path Teacher", learner: "You", modeLabel: "Practice mode", dashboard: "Student dashboard", retry: "Try again", certification: "This is practice feedback, not an official CEFR assessment or certification.",
  },
};

const modeIcons = { conversation: "◌", grammar: "⌘", vocabulary: "✦", writing: "✎", speaking: "◖" };

async function readResponse(response, text) {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;
  const code = payload.detail;
  if (code === "AI_TEACHER_NOT_CONFIGURED") throw new Error(text.config);
  if (code === "AI_TEACHER_RATE_LIMITED") throw new Error(text.rate);
  if (code === "AI_TEACHER_UNAVAILABLE") throw new Error(text.unavailable);
  throw new Error(typeof code === "string" ? code : text.error);
}

export default function AiTeacher() {
  const [language, setLanguage] = useState("ar");
  const [sessions, setSessions] = useState([]);
  const [currentSession, setCurrentSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const text = copy[language];
  const dateLocale = language === "ar" ? "ar" : "en";
  const sortedSessions = useMemo(() => sessions, [sessions]);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/me/ai/sessions");
      const payload = await readResponse(response, copy[language]);
      setSessions(payload.sessions || []);
    } catch (loadError) {
      setError(loadError.message || copy[language].error);
    } finally {
      setLoading(false);
    }
  }, [language]);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const startSession = async (mode) => {
    setBusy(true); setError("");
    try {
      const response = await authFetch("/api/me/ai/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }),
      });
      const payload = await readResponse(response, text);
      setCurrentSession(payload.session); setMessages([payload.message]); setDraft("");
      await loadSessions();
    } catch (startError) {
      setError(startError.message || text.error);
    } finally { setBusy(false); }
  };

  const openSession = async (sessionId) => {
    setBusy(true); setError("");
    try {
      const response = await authFetch(`/api/me/ai/sessions/${sessionId}`);
      const payload = await readResponse(response, text);
      setCurrentSession(payload.session); setMessages(payload.messages || []); setDraft("");
    } catch (openError) { setError(openError.message || text.error); }
    finally { setBusy(false); }
  };

  const sendMessage = async (event) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !currentSession || busy) return;
    setBusy(true); setError("");
    try {
      const response = await authFetch(`/api/me/ai/sessions/${currentSession.id}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }),
      });
      const payload = await readResponse(response, text);
      setMessages((previous) => [...previous, payload.user_message, payload.message]);
      setCurrentSession(payload.session); setDraft("");
      const sessionsResponse = await authFetch("/api/me/ai/sessions");
      if (sessionsResponse.ok) setSessions((await sessionsResponse.json()).sessions || []);
    } catch (sendError) { setError(sendError.message || text.error); }
    finally { setBusy(false); }
  };

  return <div className="course-shell ai-teacher-shell" dir={language === "ar" ? "rtl" : "ltr"}>
    <CourseNavigation language={language} activePage="ai-teacher" onLanguageChange={() => setLanguage((value) => value === "ar" ? "en" : "ar")} />
    <main className="course-main ai-teacher-main">
      <header className="ai-teacher-header"><div><p className="ai-teacher-eyebrow">FLUENT PATH / GUIDED PRACTICE</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><div className="ai-teacher-level-mark" aria-hidden="true">✦<span>F</span></div></header>
      {error && <div className="ai-teacher-error" role="alert"><span>!</span><p>{error}</p><button type="button" onClick={() => setError("")}>{text.retry}</button></div>}
      <div className="ai-teacher-layout">
        <section className="ai-teacher-workspace">
          {!currentSession ? <>
            <div className="ai-teacher-section-heading"><span>01 / PRACTICE STUDIO</span><h2>{text.select}</h2></div>
            <div className="ai-mode-grid">{modes.map((mode) => <button type="button" className="ai-mode-card" key={mode} disabled={busy} onClick={() => startSession(mode)}>
              <span className="ai-mode-icon" aria-hidden="true">{modeIcons[mode]}</span><strong>{text[mode]}</strong><p>{text[`${mode}Desc`]}</p><i>{text.start} ↗</i>
            </button>)}</div>
            <p className="ai-speech-note">◖ {text.speakingNote}</p>
            <div className="ai-practice-disclaimer">{text.certification}</div>
          </> : <>
            <div className="ai-session-heading"><div><button className="ai-back-button" type="button" onClick={() => { setCurrentSession(null); setMessages([]); setError(""); }}>{text.back}</button><p className="ai-teacher-eyebrow">{text.modeLabel} / {text[currentSession.mode]}</p><h2>{text[currentSession.mode]}</h2><span>{text.level}: {currentSession.cefr_level || text.noLevel}</span></div><span className={`ai-session-status ${currentSession.status}`}>{currentSession.status === "completed" ? text.completed : text.active}</span></div>
            <div className="ai-message-list" aria-live="polite">{messages.map((message) => <article key={message.id} className={`ai-message ${message.role}`}>
              <span className="ai-message-speaker">{message.role === "assistant" ? text.assistant : text.learner}</span>
              <p className="ai-message-content">{message.content}</p>
              {message.role === "assistant" && (message.feedback || message.corrections?.length || message.next_step || (message.score !== null && message.score !== undefined) || message.xp_awarded > 0 || message.grammar_feedback || message.vocabulary_feedback || message.clarity_feedback || message.relevance_feedback) && <div className="ai-feedback-panel">
                {message.feedback && <div><strong>{text.feedback}</strong><p>{message.feedback}</p></div>}
                {message.score !== null && message.score !== undefined && <div className="ai-score-chip">{text.score}: {message.score}/100</div>}
                {["grammar_feedback", "vocabulary_feedback", "clarity_feedback", "relevance_feedback"].filter((key) => message[key]).map((key) => <div key={key}><strong>{text[key]}</strong><p>{message[key]}</p></div>)}
                {!!message.corrections?.length && <div><strong>{text.corrections}</strong><ul>{message.corrections.map((correction, index) => <li key={`${index}-${correction}`}>{correction}</li>)}</ul></div>}
                {message.next_step && <div><strong>{text.next}</strong><p>{message.next_step}</p></div>}
                {message.xp_awarded > 0 && <span className="ai-xp-chip">✦ +{message.xp_awarded} {text.xp}</span>}
              </div>}
            </article>)}</div>
            <form className="ai-composer" onSubmit={sendMessage}><label htmlFor="ai-response">{text.prompt}</label><textarea id="ai-response" value={draft} maxLength={1500} rows={4} placeholder={text.placeholder} onChange={(event) => setDraft(event.target.value)} /><div><small>{draft.length}/1500</small><button type="submit" disabled={busy || !draft.trim()}>{busy ? text.sending : text.send} ↗</button></div></form>
          </>}
        </section>
        <aside className="ai-history-panel"><div className="ai-teacher-section-heading"><span>02 / YOUR PRACTICE</span><h2>{text.history}</h2></div>
          {loading ? <p className="ai-history-empty">{text.loading}</p> : sortedSessions.length ? <div className="ai-history-list">{sortedSessions.map((session) => <button type="button" className={`ai-history-item ${currentSession?.id === session.id ? "selected" : ""}`} key={session.id} disabled={busy} onClick={() => openSession(session.id)}>
            <span className="ai-history-icon">{modeIcons[session.mode]}</span><span><strong>{text[session.mode]}</strong><small>{new Intl.DateTimeFormat(dateLocale, { dateStyle: "medium" }).format(new Date(session.created_at))}</small></span><i>↗</i>
          </button>)}</div> : <p className="ai-history-empty">{text.noHistory}</p>}
          <Link className="ai-dashboard-link" to="/student-dashboard">← {text.dashboard}</Link>
        </aside>
      </div>
    </main>
  </div>;
}
