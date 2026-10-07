import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch } from "../auth";
import { HomeworkCard, HomeworkNavigation, HomeworkState } from "./HomeworkComponents";
import "./Homework.css";

const copy = {
  ar: { title: "واجباتي", subtitle: "راجع تعليمات المعلم ومواعيد التسليم وحالة كل واجب.", empty: "لا توجد واجبات مسندة إليك حاليًا.", loading: "جارٍ تحميل الواجبات...", retry: "إعادة المحاولة", assigned: "واجبات مسندة", dashboard: "لوحة الطالب" },
  en: { title: "My homework", subtitle: "Review teacher instructions, due dates, and each submission status.", empty: "No homework has been assigned to you yet.", loading: "Loading homework...", retry: "Try again", assigned: "Assigned items", dashboard: "Student dashboard" },
};

function StudentHomework() {
  const [language, setLanguage] = useState("ar");
  const [homework, setHomework] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const text = copy[language];

  const loadHomework = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch("/api/student/homework");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || text.retry);
      setHomework(payload.homework || []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [text.retry]);

  useEffect(() => { loadHomework(); }, [loadHomework]);

  return <div className="homework-layout" dir={language === "ar" ? "rtl" : "ltr"}>
    <HomeworkNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="homework-main">
      <header className="homework-page-header"><div><p className="homework-eyebrow">FLUENT PATH / PRACTICE</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><Link className="homework-back-link" to="/student-dashboard">{text.dashboard} ↗</Link></header>
      <div className="homework-section-heading"><h2>{text.assigned}</h2><span>{homework.length}</span></div>
      {loading ? <HomeworkState language={language}>{text.loading}</HomeworkState> : error ? <HomeworkState language={language} error={error} onRetry={loadHomework} /> : homework.length ? <div className="homework-card-grid">{homework.map((item) => <HomeworkCard key={item.id} homework={item} language={language} />)}</div> : <HomeworkState language={language}>{text.empty}</HomeworkState>}
    </main>
  </div>;
}

export default StudentHomework;
