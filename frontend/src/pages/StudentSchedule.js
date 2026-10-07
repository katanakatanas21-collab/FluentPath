import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../auth";
import { ClassCard, ClassNavigation, ClassState } from "./ClassComponents";
import "./Class.css";

const copy = {
  ar: { title: "جدولي الدراسي", subtitle: "حصصك القادمة وسجل الحصص السابقة.", upcoming: "القادمة", past: "السابقة", cancelled: "الملغاة", loading: "جارٍ تحميل الجدول...", emptyUpcoming: "لا توجد حصص قادمة مسندة إليك.", emptyPast: "لا توجد حصص سابقة.", emptyCancelled: "لا توجد حصص ملغاة.", dashboard: "لوحة الطالب" },
  en: { title: "My schedule", subtitle: "Your upcoming classes and past sessions.", upcoming: "Upcoming", past: "Past", cancelled: "Cancelled", loading: "Loading your schedule...", emptyUpcoming: "No upcoming classes are assigned to you.", emptyPast: "No past classes.", emptyCancelled: "No cancelled classes.", dashboard: "Student dashboard" },
};

function StudentSchedule() {
  const [language, setLanguage] = useState("ar");
  const [schedule, setSchedule] = useState({ upcoming: [], past: [], cancelled: [] });
  const [tab, setTab] = useState("upcoming");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const text = copy[language];

  const loadSchedule = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/student/classes");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to load schedule");
      setSchedule({ upcoming: payload.upcoming || [], past: payload.past || [], cancelled: payload.cancelled || [] });
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSchedule(); }, [loadSchedule]);
  const items = schedule[tab];
  const empty = tab === "upcoming" ? text.emptyUpcoming : tab === "past" ? text.emptyPast : text.emptyCancelled;

  return <div className="class-layout" dir={language === "ar" ? "rtl" : "ltr"}>
    <ClassNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="class-main">
      <header className="class-page-header"><div><p className="class-eyebrow">FLUENT PATH / SCHEDULE</p><h1>{text.title}</h1><p>{text.subtitle}</p></div></header>
      <div className="class-tabs" role="tablist">{["upcoming", "past", "cancelled"].map((key) => <button type="button" role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}>{text[key]} <span>{schedule[key].length}</span></button>)}</div>
      {loading ? <ClassState language={language} loading>{text.loading}</ClassState> : error ? <ClassState language={language} error={error} onRetry={loadSchedule} /> : items.length ? <div className="class-card-grid">{items.map((item) => <ClassCard key={item.id} classItem={item} language={language} />)}</div> : <ClassState language={language}>{empty}</ClassState>}
    </main>
  </div>;
}

export default StudentSchedule;
