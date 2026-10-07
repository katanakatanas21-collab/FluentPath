import StudentDashboard from "./pages/StudentDashboard";
import { useState } from "react";
import { Routes, Route, Link } from "react-router-dom";
import TrialTest from "./pages/TrialTest";
import Register from "./pages/Register";
import Courses from "./pages/Courses";
import CourseDetails from "./pages/CourseDetails";
import Login from "./pages/Login";
import ProtectedRoute from "./pages/ProtectedRoute";
import TeacherDashboard from "./pages/TeacherDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import Profile from "./pages/Profile";
import StaffProfile from "./pages/StaffProfile";
import StudentHomework from "./pages/StudentHomework";
import StudentHomeworkDetails from "./pages/StudentHomeworkDetails";
import TeacherHomework from "./pages/TeacherHomework";
import TeacherHomeworkSubmissions from "./pages/TeacherHomeworkSubmissions";
import StudentSchedule from "./pages/StudentSchedule";
import ClassDetails from "./pages/ClassDetails";
import TeacherClasses from "./pages/TeacherClasses";
import TeacherClassForm from "./pages/TeacherClassForm";
import CommunityPage from "./pages/CommunityPage";
import MessagesPage from "./pages/MessagesPage";
import AdminCommunityPage from "./pages/AdminCommunityPage";
import AdminMessagesPage from "./pages/AdminMessagesPage";
import AchievementsPage from "./pages/AchievementsPage";
import NotificationsPage from "./pages/Notifications";
import AdminCMS from "./pages/AdminCMS";
import StudentLesson from "./pages/StudentLesson";
import AiTeacher from "./pages/AiTeacher";
import "./Home.css";
function Home() {
  const [language, setLanguage] = useState("ar");
  const ar = language === "ar";
  return <div className="home-page" dir={ar ? "rtl" : "ltr"}>
    <header className="home-header">
      <Link className="home-brand" to="/"><span className="home-brand-mark">F</span><span><strong>Fluent Path</strong><small>{ar ? "تعلّم • مارس • تقدّم" : "Learn • Practice • Progress"}</small></span></Link>
      <nav className="home-actions" aria-label={ar ? "التنقل" : "Navigation"}>
        <Link className="home-signin" to="/login">{ar ? "تسجيل الدخول" : "Sign in"}</Link>
        <button className="home-language" onClick={() => setLanguage(ar ? "en" : "ar")} type="button">{ar ? "English" : "العربية"}</button>
      </nav>
    </header>
    <main className="home-hero">
      <div className="home-copy">
        <span className="home-kicker">{ar ? "مسار متقن نحو الإنجليزية" : "A considered path to English"}</span>
        <h1>{ar ? "طريقك إلى إتقان اللغة الإنجليزية" : "Your path to English mastery"}</h1>
        <p>{ar ? "تعلّم، مارس، وتابع تقدمك خطوة بخطوة في تجربة تعليمية مصممة لتناسب مستواك." : "Learn, practice, and track your progress step by step in a learning experience shaped around your level."}</p>
        <Link className="home-cta" to="/register" state={{ language }}>{ar ? "أنشئ حسابًا وابدأ التعلّم" : "Create an account to get started"}<span aria-hidden="true">↗</span></Link>
      </div>
      <div className="home-arch" aria-hidden="true"><div className="home-arch-inner"><span>F</span><i /></div></div>
    </main>
    <footer className="home-footer"><span>FLUENT PATH</span><span>{ar ? "تعلّم بثقة، خطوة بخطوة" : "Learn with confidence, one step at a time"}</span></footer>
  </div>;
}

function NotFound() {
  return <main className="route-state" dir="auto"><span className="route-state-mark">F</span><h1>Page not found · الصفحة غير موجودة</h1><p>The address may have changed, or the page is unavailable.</p><Link to="/">Return home · العودة للرئيسية</Link></main>;
}

function App() {
  return (
  <Routes>
  <Route path="/" element={<Home />} />
  <Route path="/register" element={<Register />} />
  <Route path="/login" element={<Login />} />
  <Route path="/trial-test" element={<ProtectedRoute roles={["student"]}><TrialTest /></ProtectedRoute>} />
  <Route path="/student-dashboard" element={<ProtectedRoute roles={["student"]}><StudentDashboard /></ProtectedRoute>} />
  <Route path="/ai-teacher" element={<ProtectedRoute roles={["student"]}><AiTeacher /></ProtectedRoute>} />
  <Route path="/courses" element={<ProtectedRoute roles={["student"]}><Courses /></ProtectedRoute>} />
  <Route path="/courses/:courseId" element={<ProtectedRoute roles={["student"]}><CourseDetails /></ProtectedRoute>} />
  <Route path="/courses/:courseId/lessons/:lessonId" element={<ProtectedRoute roles={["student"]}><StudentLesson /></ProtectedRoute>} />
  <Route path="/profile" element={<ProtectedRoute roles={["student"]}><Profile /></ProtectedRoute>} />
  <Route path="/achievements" element={<ProtectedRoute roles={["student"]}><AchievementsPage /></ProtectedRoute>} />
  <Route path="/notifications" element={<ProtectedRoute roles={["student", "teacher", "administrator"]}><NotificationsPage /></ProtectedRoute>} />
  <Route path="/homework" element={<ProtectedRoute roles={["student"]}><StudentHomework /></ProtectedRoute>} />
  <Route path="/homework/:homeworkId" element={<ProtectedRoute roles={["student"]}><StudentHomeworkDetails /></ProtectedRoute>} />
  <Route path="/schedule" element={<ProtectedRoute roles={["student"]}><StudentSchedule /></ProtectedRoute>} />
  <Route path="/classes/:classId" element={<ProtectedRoute roles={["student"]}><ClassDetails /></ProtectedRoute>} />
  <Route path="/community" element={<ProtectedRoute roles={["student", "teacher"]}><CommunityPage /></ProtectedRoute>} />
  <Route path="/messages" element={<ProtectedRoute roles={["student", "teacher"]}><MessagesPage /></ProtectedRoute>} />
  <Route path="/teacher-dashboard" element={<ProtectedRoute roles={["teacher"]}><TeacherDashboard /></ProtectedRoute>} />
  <Route path="/teacher-classes" element={<ProtectedRoute roles={["teacher"]}><TeacherClasses /></ProtectedRoute>} />
  <Route path="/teacher-classes/new" element={<ProtectedRoute roles={["teacher"]}><TeacherClassForm /></ProtectedRoute>} />
  <Route path="/teacher-classes/:classId/edit" element={<ProtectedRoute roles={["teacher"]}><TeacherClassForm /></ProtectedRoute>} />
  <Route path="/admin-community" element={<ProtectedRoute roles={["administrator"]}><AdminCommunityPage /></ProtectedRoute>} />
  <Route path="/admin-community/reports" element={<ProtectedRoute roles={["administrator"]}><AdminCommunityPage initialView="reports" /></ProtectedRoute>} />
  <Route path="/admin-messages" element={<ProtectedRoute roles={["administrator"]}><AdminMessagesPage /></ProtectedRoute>} />
  <Route path="/teacher-homework" element={<ProtectedRoute roles={["teacher"]}><TeacherHomework /></ProtectedRoute>} />
  <Route path="/teacher-homework/:homeworkId/submissions" element={<ProtectedRoute roles={["teacher"]}><TeacherHomeworkSubmissions /></ProtectedRoute>} />
  <Route path="/admin-dashboard" element={<ProtectedRoute roles={["administrator"]}><AdminDashboard /></ProtectedRoute>} />
  <Route path="/admin-content" element={<ProtectedRoute roles={["administrator"]}><AdminCMS /></ProtectedRoute>} />
  <Route path="/admin-content/courses/new" element={<ProtectedRoute roles={["administrator"]}><AdminCMS mode="course-form" /></ProtectedRoute>} />
  <Route path="/admin-content/courses/:courseId/edit" element={<ProtectedRoute roles={["administrator"]}><AdminCMS mode="course-form" /></ProtectedRoute>} />
  <Route path="/admin-content/courses/:courseId/lessons/new" element={<ProtectedRoute roles={["administrator"]}><AdminCMS mode="lesson-form" /></ProtectedRoute>} />
  <Route path="/admin-content/courses/:courseId/lessons/:lessonId/edit" element={<ProtectedRoute roles={["administrator"]}><AdminCMS mode="lesson-form" /></ProtectedRoute>} />
  <Route path="/admin-content/courses/:courseId" element={<ProtectedRoute roles={["administrator"]}><AdminCMS mode="course" /></ProtectedRoute>} />
  <Route path="/teacher-profile" element={<ProtectedRoute roles={["teacher"]}><StaffProfile role="teacher" /></ProtectedRoute>} />
  <Route path="/administrator-profile" element={<ProtectedRoute roles={["administrator"]}><StaffProfile role="administrator" /></ProtectedRoute>} />
  <Route path="*" element={<NotFound />} />
</Routes>
  );
}

export default App;
