# RanuConstruction

## Consultation form email

The interiors consultation form sends its submitted details to
`info@ranugroupindia.com` through the FastAPI backend. For production, point the
Vercel `/api/*` rewrite in `vercel.json` at the deployed backend and configure
`EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
and `SMTP_FROM` in the backend environment. Do not put SMTP credentials in
frontend code. The endpoint returns an error instead of reporting success when
email delivery is not configured or fails.