export function StaffStat({ icon, label, value, detail }) {
  return <article className="staff-stat"><span className="staff-stat-icon">{icon}</span><span className="staff-stat-label">{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

export function StaffState({ message, error, onRetry }) {
  return <div className="staff-state"><div className="staff-state-card"><span>{error ? "!" : "F"}</span><h2>{error ? "Could not load this area" : "Loading Fluent Path"}</h2><p>{message}</p>{error && <button type="button" onClick={onRetry}>Try again</button>}</div></div>;
}

export function MvpNotice({ children }) {
  return <div className="mvp-notice"><span>MVP</span>{children}</div>;
}
