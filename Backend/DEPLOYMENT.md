# Masar deployment checklist

## Backend
- [ ] PostgreSQL/Neon database is reachable from the host; set `DATABASE_URL` in the platform secret manager.
- [ ] Set a strong **`AUTH_SECRET`** (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- [ ] Set `FRONTEND_ORIGINS` to the exact deployed frontend origin(s). Use `FRONTEND_ORIGIN_REGEX` only for preview URLs you trust.
- [ ] E-mail: set `EMAIL_PROVIDER` (+ Resend/SMTP settings). For Resend, **verify your sending domain** - otherwise it only delivers to your own account address and users never receive codes. Keep `EMAIL_DEV_CONSOLE=false`.
- [ ] Keep `ALLOW_DIRECT_SIGNUP=false`.
- [ ] Run `python seed_db.py` once to create/upgrade the schema and load/update the catalog.
- [ ] Run a single server process (rate limits are in memory), or move rate limiting to a gateway/Redis.
- [ ] Verify `/health`, then `/system/config` (shows whether AI explanations are enabled).
- [ ] Optional AI: `AI_EXPLANATION_ENABLED=true`, `AI_API_KEY`; keep `AI_EXPLANATION_TIMEOUT_SECONDS` >= 5.

## Frontend
- [ ] Set `NEXT_PUBLIC_API_URL` to the public FastAPI URL (HTTPS).
- [ ] `npm install` then `npm run build` in CI; deploy with the included Netlify configuration or the host's Next.js integration.

## Before public launch
- [ ] HTTPS on frontend and backend; never commit `.env` / `.env.local`.
- [ ] Rotate any key that was ever shared in a zip, chat or repository.
- [ ] Do not keep synthetic accounts (`999xxxxxx`, known password) in a real database: `python generate_synthetic_students.py --cleanup`.
- [ ] Consider object storage for profile photos if the user base grows (data URLs in the database are fine for the prototype).
- [ ] Real student data falls under UAE Federal Decree-Law 45/2021 (personal data protection).
