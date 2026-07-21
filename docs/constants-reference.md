# PFIS Constants Reference

## Settings

Defined in `backend/app/config.py`:

- `APP_NAME`
- `APP_VERSION`
- `DEBUG`
- `DATABASE_URL`
- `SECRET_KEY`
- `TOKEN_ENCRYPTION_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `AUTH_REQUIRED`
- `SESSION_COOKIE_NAME`
- `CSRF_COOKIE_NAME`
- `OAUTH_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `SESSION_ABSOLUTE_HOURS`
- `SESSION_IDLE_MINUTES`
- `PASSWORD_MIN_LENGTH`
- `ALLOW_DEMO_LOGIN`
- `CORS_ORIGINS`
- `DEMO_USER_PASSWORD`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GMAIL_OAUTH_REDIRECT_URI`
- `GOOGLE_ALLOWED_EMAILS`

## Parser Thresholds

- Low-confidence threshold: below `0.7` in pipeline stats.
- Merchant cache TTL: defined in `normalizer.py`.
- Minimal valid parse: amount and transaction type.

## API Limits

Route-level limits are defined through FastAPI `Query` constraints and slowapi decorators where present.

