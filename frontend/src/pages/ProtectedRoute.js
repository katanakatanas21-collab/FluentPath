import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { authFetch, clearAuthSession, getAccessToken } from "../auth";
import { Link } from "react-router-dom";

function AccessDenied({ role }) {
  const destination = role === "student" ? "/student-dashboard" : role === "teacher" ? "/teacher-dashboard" : "/admin-dashboard";
  return <main className="route-state" dir="auto"><span className="route-state-mark">F</span><h1>Access unavailable · الوصول غير متاح</h1><p>Your account does not have permission to open this page.</p><Link to={destination}>Return to your dashboard · العودة إلى لوحة التحكم</Link></main>;
}

function ProtectedRoute({ children, roles }) {
  const location = useLocation();
  const [state, setState] = useState({ loading: true, user: null, error: "", path: null });

  useEffect(() => {
    let active = true;
    const loadUser = async () => {
      if (!getAccessToken()) {
        if (active) setState({ loading: false, user: null, error: "", path: location.pathname });
        return;
      }
      try {
        const response = await authFetch("/api/me");
        const data = await response.json();
        if (!response.ok) {
          if (response.status === 401) clearAuthSession();
          throw new Error(data.detail || "Authentication failed");
        }
        if (active) setState({ loading: false, user: data, error: "", path: location.pathname });
      } catch (error) {
        if (active) setState({ loading: false, user: null, error: error.message, path: location.pathname });
      }
    };
    loadUser();
    return () => { active = false; };
  }, [location.pathname]);

  if (state.loading || state.path !== location.pathname) return <div className="auth-state"><div className="loading-spinner" /><p>جارٍ التحقق من الجلسة...</p></div>;
  if (!state.user) return <Navigate to="/login" replace state={{ from: location.pathname, error: state.error }} />;
  if (roles && !roles.includes(state.user.role)) return <AccessDenied role={state.user.role} />;
  if (
    state.user.role === "student"
    && !state.user.level
    && !state.user.testCompletedAt
    && location.pathname !== "/trial-test"
  ) {
    return <Navigate to="/trial-test" replace state={{ autoStartPlacementTest: true }} />;
  }

  return children;
}

export default ProtectedRoute;
