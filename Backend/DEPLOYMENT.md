# Masar deployment checklist

## Backend
- PostgreSQL/Neon database is reachable from the deployment environment.
- Set `DATABASE_URL` using the platform secret manager.
- Set `FRONTEND_ORIGINS` to the exact deployed frontend origin(s), comma-separated.
- Run `python seed_db.py` once against the target database to load/update the course catalog and prerequisite relationships.
- Expose port 8000 (or the platform-provided `$PORT` if the host requires it).
- Verify `/health` returns a connected database status.

## Frontend
- Set `NEXT_PUBLIC_API_URL` to the public FastAPI URL.
- Run `npm install` and `npm run build` in CI.
- Deploy the Next.js output using the included Netlify configuration or the host's native Next.js integration.

## Security before public launch
- Use HTTPS for both frontend and backend.
- Keep `DATABASE_URL` out of source control.
- Replace the prototype forgot-password handoff with a real verified email/token flow before production account recovery.
- Consider moving profile images to object storage if the user base grows substantially; the current database data-URL approach is appropriate for the prototype.
