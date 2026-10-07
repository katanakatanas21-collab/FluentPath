# Engineering Rules

- Preserve working functionality; do not rewrite working modules without a clear reason.
- Keep the existing React frontend and FastAPI backend architecture.
- Use the existing authentication flow and server-side role authorization.
- Never trust user IDs or roles supplied by the frontend; derive identity and role from the authenticated server-side user.
- Never expose passwords or password hashes.
- Store persistent product data through the backend.
- Preserve Arabic RTL and English LTR support and responsive desktop, tablet, and mobile layouts.
- Prefer reusable components and avoid duplicate APIs or data models.
- Run the smallest relevant test or build after each feature, and fix errors caused by your changes.
- Do not mark unfinished functionality complete. Clearly distinguish MVP placeholders from implemented functionality.
- Verify security implications before production-related changes.
