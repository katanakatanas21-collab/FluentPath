import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { API_URL, setAuthSession } from "../auth";

function Register() {
  const navigate = useNavigate();
  const location = useLocation();
  const [language, setLanguage] = useState(location.state?.language === "en" ? "en" : "ar");
  const ar = language === "ar";
  const copy = ar ? {
    title: "إنشاء حساب طالب", intro: "أنشئ حسابك ثم ابدأ اختبار تحديد المستوى.", fullName: "الاسم الكامل",
    namePlaceholder: "اكتب اسمك الكامل", email: "البريد الإلكتروني", password: "كلمة المرور",
    passwordPlaceholder: "6 أحرف على الأقل", birthDate: "تاريخ الميلاد", phone: "رقم الهاتف",
    optional: "(اختياري)", phonePlaceholder: "+968 XXXXXXXX", submit: "إنشاء الحساب وبدء الاختبار",
    loading: "جارٍ إنشاء الحساب...", home: "العودة إلى الصفحة الرئيسية", existing: "لديك حساب بالفعل؟",
    login: "تسجيل الدخول", networkError: "تعذر الوصول إلى الخدمة الآن. حاول مرة أخرى.", createError: "حدث خطأ أثناء إنشاء الحساب",
  } : {
    title: "Create a student account", intro: "Create your account, then begin the placement test.", fullName: "Full name",
    namePlaceholder: "Enter your full name", email: "Email address", password: "Password",
    passwordPlaceholder: "At least 6 characters", birthDate: "Date of birth", phone: "Phone number",
    optional: "(optional)", phonePlaceholder: "+968 XXXXXXXX", submit: "Create account and start test",
    loading: "Creating account…", home: "Back to home", existing: "Already have an account?",
    login: "Sign in", networkError: "The service could not be reached. Please try again.", createError: "Could not create the account.",
  };

  const [formData, setFormData] = useState({
    fullName: "",
    email: "",
    password: "",
    dateOfBirth: "",
    phone: "",
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleChange = (e) => {
    const { name, value } = e.target;

    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/api/register`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(formData),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(ar
          ? data.detail || copy.createError
          : response.status === 400
            ? "An account with this email already exists."
            : copy.createError);
      }

      setAuthSession(data.access_token);

      navigate("/trial-test", { state: { autoStartPlacementTest: true, language } });
    } catch (err) {
      setError(err.message === "Failed to fetch" ? copy.networkError : err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      dir={ar ? "rtl" : "ltr"}
      style={{
        minHeight: "100vh",
        background:
          "linear-gradient(135deg, var(--fp-canvas) 0%, #ffffff 50%, var(--fp-surface-muted) 100%)",
        padding: "60px 20px",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "600px",
          width: "100%",
          boxSizing: "border-box",
          margin: "0 auto",
          background: "#ffffff",
          padding: "40px",
          borderRadius: "24px",
          boxShadow: "0 15px 40px rgba(0,0,0,0.08)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
          <button type="button" onClick={() => setLanguage(ar ? "en" : "ar")} style={{ border: "1px solid var(--fp-border)", borderRadius: "9px", padding: "9px 14px", background: "#fff", color: "var(--fp-muted)", cursor: "pointer" }}>
            {ar ? "English" : "العربية"}
          </button>
        </div>
        <div style={{ textAlign: "center", marginBottom: "30px" }}>
          <h1
            style={{
              margin: "0 0 10px",
              color: "var(--fp-primary)",
              fontSize: "36px",
            }}
          >
            Fluent Path
          </h1>

          <h2 style={{ margin: "0 0 10px" }}>
            {copy.title}
          </h2>

          <p style={{ color: "var(--fp-muted)" }}>
            {copy.intro}
          </p>
        </div>

        {error && (
          <div
            style={{
              marginBottom: "20px",
              padding: "12px",
              borderRadius: "10px",
              background: "#fee2e2",
              color: "#b91c1c",
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label>{copy.fullName}</label>

          <input
            type="text"
            name="fullName"
            value={formData.fullName}
            onChange={handleChange}
            required
            placeholder={copy.namePlaceholder}
            style={inputStyle}
          />

          <label>{copy.email}</label>

          <input
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            required
            placeholder="example@email.com"
            style={inputStyle}
          />

          <label>{copy.password}</label>

          <input
            type="password"
            name="password"
            value={formData.password}
            onChange={handleChange}
            required
            minLength={6}
            placeholder={copy.passwordPlaceholder}
            style={inputStyle}
          />

          <label>{copy.birthDate}</label>

          <input
            type="date"
            name="dateOfBirth"
            value={formData.dateOfBirth}
            onChange={handleChange}
            required
            style={inputStyle}
          />

          <label>
            {copy.phone}
            <span style={{ color: "#94a3b8", fontWeight: "normal" }}>
              {" "}
              {copy.optional}
            </span>
          </label>

          <input
            type="tel"
            name="phone"
            value={formData.phone}
            onChange={handleChange}
            placeholder={copy.phonePlaceholder}
            style={inputStyle}
          />

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              marginTop: "20px",
              padding: "15px",
              border: "none",
              borderRadius: "12px",
              background: loading ? "#94a3b8" : "var(--fp-primary)",
              color: "#ffffff",
              fontSize: "18px",
              fontWeight: "700",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading
              ? copy.loading
              : copy.submit}
          </button>
        </form>

        <div
          style={{
            textAlign: "center",
            marginTop: "20px",
          }}
        >
          <Link
            to="/"
            style={{
              color: "var(--fp-primary)",
              textDecoration: "none",
            }}
          >
            {copy.home}
          </Link>
        </div>

        <div style={{ textAlign: "center", marginTop: "14px", color: "var(--fp-muted)" }}>
          {copy.existing} <Link to="/login" state={{ language }} style={{ color: "var(--fp-primary)", textDecoration: "none" }}>{copy.login}</Link>
        </div>
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "13px",
  marginTop: "8px",
  marginBottom: "18px",
  border: "1px solid #cbd5e1",
  borderRadius: "10px",
  fontSize: "16px",
  boxSizing: "border-box",
};

export default Register;
