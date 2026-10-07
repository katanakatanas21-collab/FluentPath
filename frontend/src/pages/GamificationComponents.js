import { Link } from "react-router-dom";
import "./Gamification.css";

const text = {
  ar: {
    xp: "نقاط الخبرة", level: "المستوى", nextLevel: "المستوى التالي", maxLevel: "أعلى مستوى",
    toNext: "متبقية للمستوى التالي", streak: "سلسلة التعلم", current: "السلسلة الحالية",
    longest: "أطول سلسلة", days: "يوم", earned: "مكتسب", locked: "مقفل",
    achievements: "إنجازاتي الأخيرة", allAchievements: "عرض كل الإنجازات", leaderboard: "لوحة المتصدرين",
    rank: "الترتيب", learner: "المتعلم", empty: "ابدأ التعلم لفتح إنجازك الأول.",
  },
  en: {
    xp: "Experience points", level: "Level", nextLevel: "Next level", maxLevel: "Maximum level",
    toNext: "to next level", streak: "Learning streak", current: "Current streak",
    longest: "Longest streak", days: "days", earned: "Earned", locked: "Locked",
    achievements: "Recent achievements", allAchievements: "View all achievements", leaderboard: "Leaderboard",
    rank: "Rank", learner: "Learner", empty: "Start learning to earn your first badge.",
  },
};

export function XPCard({ data = {}, language = "en" }) {
  const copy = text[language] || text.en;
  return <article className="gamification-card xp-card"><span className="gamification-card-label">{copy.xp}</span><strong className="xp-total">{data.xp || 0}<small> XP</small></strong><span className="gamification-level">{copy.level} {data.level || 1}</span></article>;
}

export function LevelProgress({ data = {}, language = "en" }) {
  const copy = text[language] || text.en;
  const progress = data.levelProgress || {};
  const percent = progress.progressPercent || 0;
  return <article className="gamification-card level-card"><div className="gamification-card-heading"><span className="gamification-card-label">{copy.level} {data.level || 1}</span><span>{progress.nextLevel ? `${copy.nextLevel} ${progress.nextLevel}` : copy.maxLevel}</span></div><div className="level-track" role="progressbar" aria-label={copy.level} aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100"><span style={{ width: `${percent}%` }} /></div><div className="level-progress-meta"><span>{progress.xpIntoLevel || 0} XP</span><span>{progress.nextLevelXp ? `${progress.xpToNextLevel} ${copy.toNext}` : copy.maxLevel}</span></div></article>;
}

export function StreakCard({ data = {}, language = "en" }) {
  const copy = text[language] || text.en;
  return <article className="gamification-card streak-card"><span className="gamification-card-label">{copy.streak}</span><div className="streak-values"><strong>✦ {data.currentStreak || 0}<small> {copy.days}</small></strong><span>{copy.current}</span></div><div className="streak-longest">{copy.longest}: <strong>{data.longestStreak || 0} {copy.days}</strong></div></article>;
}

export function BadgeCard({ badge, language = "en" }) {
  const copy = text[language] || text.en;
  if (!badge) return null;
  const ar = language === "ar";
  return <article className={`badge-card ${badge.earned === false ? "badge-locked" : "badge-earned"}`}><span className="badge-icon" aria-hidden="true">{badge.icon || "★"}</span><div><h3>{ar ? badge.titleAr : badge.title}</h3><p>{ar ? badge.descriptionAr : badge.description}</p><small>{badge.earned === false ? copy.locked : copy.earned}</small></div></article>;
}

export function Leaderboard({ entries = [], language = "en", preview = false }) {
  const copy = text[language] || text.en;
  const visible = preview ? entries.slice(0, 5) : entries;
  return <section className="gamification-card leaderboard-card"><div className="gamification-section-heading"><h2>{copy.leaderboard}</h2></div>{visible.length ? <ol className="leaderboard-list">{visible.map((entry) => <li key={`${entry.rank}-${entry.displayName}`}><span className="leaderboard-rank">{entry.rank}</span><strong>{entry.displayName}</strong><span className="leaderboard-level">{copy.level} {entry.level}</span><b>{entry.xp} XP</b></li>)}</ol> : <p className="gamification-empty">—</p>}</section>;
}

export function AchievementSection({ badges = [], language = "en", link = true }) {
  const copy = text[language] || text.en;
  const earned = badges.filter((badge) => badge.earned !== false);
  return <section className="gamification-card achievement-section"><div className="gamification-section-heading"><h2>{copy.achievements}</h2>{link && <Link to="/achievements">{copy.allAchievements} ↗</Link>}</div>{earned.length ? <div className="badge-grid">{earned.slice(0, 4).map((badge) => <BadgeCard key={badge.id} badge={badge} language={language} />)}</div> : <p className="gamification-empty">{copy.empty}</p>}</section>;
}
