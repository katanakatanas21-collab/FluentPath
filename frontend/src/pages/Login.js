import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_URL, setAuthSession } from "../auth";
import "./Auth.css";

function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [language, setLanguage] = useState(location.state?.language === "en" ? "en" : "ar");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(location.state?.error || "");
  const ar = language === "ar";

  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || (ar ? "بيانات الدخول غير صحيحة" : "Invalid credentials"));
      setAuthSession(data.access_token);
      const placementRequired = data.user.role === "student" && !data.user.level && !data.user.testCompletedAt;
      const destination = placementRequired
        ? "/trial-test"
        : location.state?.from?.startsWith("/")
          ? location.state.from
          : data.user.role === "student"
            ? "/student-dashboard"
            : data.user.role === "teacher"
              ? "/teacher-dashboard"
              : "/admin-dashboard";
      navigate(destination, {
        replace: true,
        state: placementRequired ? { autoStartPlacementTest: true } : undefined,
      });
    } catch (loginError) {
      setError(loginError.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page" dir={ar ? "rtl" : "ltr"}>
      <div className="auth-topbar"><Link to="/" className="auth-brand">Fluent Path</Link><button type="button" onClick={() => setLanguage(ar ? "en" : "ar")}>{ar ? "English" : "العربية"}</button></div>
      <main className="auth-card"><div className="auth-mark">F</div><p className="auth-eyebrow">FLUENT PATH / ACCESS</p><h1>{ar ? "تسجيل الدخول" : "Sign in"}</h1><p className="auth-intro">{ar ? "تابع رحلة تعلم الإنجليزية من حيث توقفت." : "Continue your English learning journey."}</p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="login-email">{ar ? "البريد الإلكتروني" : "Email"}</label><input id="login-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" />
          <label htmlFor="login-password">{ar ? "كلمة المرور" : "Password"}</label><input id="login-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required autoComplete="current-password" />
          <button className="auth-submit" type="submit" disabled={loading}>{loading ? (ar ? "جارٍ الدخول..." : "Signing in...") : (ar ? "دخول" : "Sign in")}</button>
        </form>
        <p className="auth-footnote">{ar ? "ليس لديك حساب؟" : "New to Fluent Path?"} <Link to="/register" state={{ language }}>{ar ? "إنشاء حساب" : "Create an account"}</Link></p>
      </main>
    </div>
  );
}

export default Login;
