import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { authFetch } from "../auth";
import { ClassNavigation, ClassState, ClassStatus, formatClassDate } from "./ClassComponents";
import "./Class.css";

const copy = {
  ar: { title: "تفاصيل الحصة", teacher: "المعلم", course: "الدورة والمستوى", date: "التاريخ والوقت", status: "الحالة", back: "العودة إلى الجدول", loading: "جارٍ تحميل تفاصيل الحصة...", join: "الانضمام إلى الحصة", noMeeting: "لم يضف المعلم رابطًا للاجتماع بعد." },
  en: { title: "Class details", teacher: "Teacher", course: "Course and level", date: "Date and time", status: "Status", back: "Back to schedule", loading: "Loading class details...", join: "Join class", noMeeting: "The teacher has not added a meeting link yet." },
};

function ClassDetails() {
  const { classId } = useParams();
  const [language, setLanguage] = useState("ar");
  const [classItem, setClassItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const text = copy[language];

  const loadClass = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await authFetch(`/api/student/classes/${classId}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to load class");
      setClassItem(payload.class);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, [classId]);

  useEffect(() => { loadClass(); }, [loadClass]);
  const courseName = language === "ar" ? classItem?.course?.titleAr || classItem?.course?.title : classItem?.course?.title;
  const meetingUrl = classItem?.studentJoinUrl || classItem?.meetingUrl;

  return <div className="class-layout" dir={language === "ar" ? "rtl" : "ltr"}>
    <ClassNavigation language={language} onLanguageChange={() => setLanguage(language === "ar" ? "en" : "ar")} />
    <main className="class-main">
      <header className="class-page-header"><div><p className="class-eyebrow">FLUENT PATH / CLASS</p><h1>{classItem?.title || text.title}</h1></div><Link to="/schedule" className="class-back-link">← {text.back}</Link></header>
      {loading ? <ClassState language={language} loading>{text.loading}</ClassState> : error ? <ClassState language={language} error={error} onRetry={loadClass} /> : classItem && <>
        <section className="class-detail-panel"><div className="class-detail-title"><div><p className="class-eyebrow">{text.title}</p><h2>{classItem.title}</h2></div><ClassStatus classItem={classItem} language={language} /></div><p className="class-description">{classItem.description || "—"}</p>
          <dl className="class-detail-grid"><div><dt>{text.teacher}</dt><dd>{classItem.teacher?.fullName || "—"}</dd></div><div><dt>{text.course}</dt><dd>{courseName || classItem.level || "—"}</dd></div><div><dt>{text.date}</dt><dd>{formatClassDate(classItem, language)} · {classItem.startTime} - {classItem.endTime}</dd></div><div><dt>{text.status}</dt><dd><ClassStatus classItem={classItem} language={language} /></dd></div></dl>
          {meetingUrl && classItem.status !== "cancelled" ? <a className="class-join-button" href={meetingUrl} target="_blank" rel="noreferrer">↗ {text.join}</a> : <p className="class-no-meeting">{text.noMeeting}</p>}
        </section>
      </>}
    </main>
  </div>;
}

export default ClassDetails;
