# RanuConstruction

## Consultation form email

The interiors consultation form sends its submitted details to
`info@ranugroupindia.com` through the FastAPI backend. The backend is configured
to use GoDaddy SMTP over implicit SSL (`smtpout.secureserver.net:465`). Set
`SMTP_PASSWORD` to the mailbox password in the backend's secret environment
variables; never commit it or place it in frontend code. The Render blueprint
contains the non-secret SMTP settings. Also point the Vercel `/api/*` rewrite
in `vercel.json` at the deployed backend. The endpoint returns an error instead
of reporting success when email delivery is not configured or fails.