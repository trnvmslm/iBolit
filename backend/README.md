# iBolit backend

Django REST API for the iBolit iOS telehealth app (university IT Project Management course).
Every Figma screen has working endpoints on demo data. **All data is fake test data.**
External services (Apple sign-in, Apple Pay, push, courier, AI) are mocks; responses that used
a mock carry `X-Provider-Mode: mock`. Video uses ZEGOCLOUD tokens when keys are set, otherwise a mock token.

## Run (Docker)

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_demo
```

- Swagger: http://localhost:8000/api/docs · raw schema: http://localhost:8000/api/schema · admin: http://localhost:8000/admin
- Export the schema to a file: `uv run python manage.py spectacular --file openapi.json --format openapi-json --validate`
- Stop: `docker compose down`


## Tests

Tests use the compose Postgres on `localhost:5433` (start it with `docker compose up -d db`).

```bash
uv sync
uv run pytest -q          # 59 tests incl. one end-to-end journey (tests/test_e2e.py)
```

## Folder map

```
src/ibolit/
  config/        settings, root URLs
  core/          errors (problem+json), permissions, pagination, clock, money, OpenAPI hook
  accounts/      phone + password auth, Apple mock, JWT, profile, preferences, devices, data export, support
  directory/     doctors, specialties, reviews, ratings          catalog/   service categories + services
  scheduling/    availability, slots, hold → confirm, cancel, reschedule (no double booking: DB constraint)
  payments/      Apple Pay mock charges, refunds, receipts
  consultations/ chat (polling), video (ZEGO), summaries (sign, amend)
  consent/       record sharing per appointment + access log    medcard/  patient medical card
  ai/            iBolit AI (keyword rules + red flags)          emergency/  103 content
  reminders/     smart reminders                                articles/  health articles
  pharmacy/      medicines, cart, prescriptions, orders         inquiries/ anonymous / intern / pharmacist questions
  notifications/ in-app notifications (push is stored only)     home/      Home screen in one call
  files/         uploads (PDF, images, voice)                   integrations/  mock providers, ZEGO tokens
  seed/          demo data (relative to "now")
tests/           pytest suite
```

Each app: `models.py` → `services.py` (rules) → `selectors.py` (reads) → `api/views.py` + `api/urls.py` (thin HTTP layer).

## Course features → endpoints (`/api/v1/…`)

| ID | Feature | Endpoints |
|---|---|---|
| F1 | Emergency 103 | `emergency`, `emergency/taps`, `home` (emergency block) |
| F2 | Doctor search and booking (taken slot → 409) | `doctors`, `providers/{id}/availability/slots`, `bookings/hold`, `bookings/{id}/confirm`, `cancel`, `reschedule` |
| F3 | Medical card (patient-only, shared via consent) | `medcard/*`, `medcard/export.pdf`, `consents`, `doctor/appointments/{id}/shared/{scope}`, `me/access-log` |
| F4 | AI chat (mock rules) | `ai/conversations`, `ai/conversations/{id}/messages` |
| F8 | Verified doctors and ratings | `doctors/{id}` (verified badge, rating breakdown), `doctors/{id}/reviews` GET/POST |

---

# API guide for the iOS app

Base URL `http://localhost:8000/api/v1/`. Send `Authorization: Bearer <access>` on every call except the public ones
(auth, `emergency`, `meta`, `services*`, `legal/privacy-policy`).

## Auth

1. `POST auth/signup {phone, password, full_name, accepted_documents: ["terms_of_service:1.0", "privacy_policy:1.0"], device_id?, device_name?}`
   → `201 {access, refresh, user}`. No SMS code: the account is created right away.
2. `POST auth/login {phone, password, device_id?, device_name?}` → `{access, refresh, user}`.
3. Change password: `POST me/password {current_password, new_password}` (logged in). There is no "forgot password" without SMS; an admin can reset it in /admin.
4. Access token lives 15 min (`ACCESS_TOKEN_MINUTES`), refresh 30 days. On 401 `authentication_failed` call
   `POST auth/token/refresh {refresh}`; it returns a **new** refresh token, so store it. The old one stops working.
5. `POST auth/logout` with the `Authorization` header and an empty body ends this device's session (`{refresh}` in the body is optional). Apple: `POST auth/apple {identity_token}` (mock token `mock-apple:<any-id>`), then `auth/apple/link {apple_link_token, phone, accepted_documents}` on the first sign-in creates the account and returns tokens (409 if the number is already registered).

Phones are accepted in any common format and returned as `+7 701 234 56 78`.

## Conventions

- JSON; times are ISO-8601 UTC. Display strings (`label`, `display`, `when`) are already formatted for Asia/Almaty.
- Money: `{"amount_minor": 1200000, "currency": "KZT", "display": "12,000 ₸"}` (`amount_minor` is tiyn, ₸ × 100). Show `display`.
- Lists: `{"items": [...], "next_cursor": "..."}`; pass `?cursor=&limit=20`; `null` cursor = end.
- `Accept-Language: en|ru|kk` localizes catalog names and error titles.

## Errors

Every error is `application/problem+json`:

```json
{"type": "https://docs.ibolit.kz/problems/slot_unavailable", "title": "This time is no longer available.",
 "status": 409, "code": "slot_unavailable", "detail": "..."}
```

Branch on `code`, show `title`. Validation errors (422) add `errors: [{field, message, code}]`.
Codes: `authentication_failed` (401, also expired token), `permission_denied` (403), `not_found` (404, also for other people's records),
`slot_unavailable`, `patient_overlap`, `hold_expired`, `out_of_stock`, `video_window_closed`, `consent_required` (409),
`payment_declined` (402), `rate_limited` (429 on auth).

## Booking flow

1. `GET doctors?recommended_for=neurologist` → cards with `next_available.offering_id`.
2. `GET providers/{id}/availability/slots?date=YYYY-MM-DD&offering={offering_id}` → `day_parts[].slots[].starts_at`.
3. `POST bookings/hold {offering_id, starts_at}` → status `held`, `hold_expires_at` (10 min), fee, total, `cancellation.free_until`.
   Lab/vaccination services: `{service_id, provider_id, starts_at}` instead of `offering_id`.
4. `POST bookings/{id}/confirm {payment_token}` with `Idempotency-Key: <uuid>` (safe to retry). Mock token: anything; `tok_declined` declines.
5. 409 `slot_unavailable` at step 3 means someone took the slot: reload slots.
6. `POST bookings/{id}/cancel {reason}` (`refund_status`: `full` or `none` when later than 2 h before). `POST bookings/{id}/reschedule {starts_at}`.

## Consultation

- Chat: poll `GET threads/{id}/messages?after_id=<last id>` every 3–5 s; `POST` `{text}` or `{file_id}` (upload first with `POST files`, multipart `file` + `purpose=chat_attachment|voice_message`).
- Video: `POST consultations/{id}/video/join` from 5 min before start → `{provider, app_id, room_id, user_id, token}`. With `provider: "zego"` pass these to the ZEGOCLOUD SDK; with `"mock"` show the call UI without media.
- Share records: `POST consents {appointment_id, scopes: ["allergies_medications", "recent_labs"]}`; revoke with `POST consents/{id}/revoke`.
- After the visit: `GET consultations/{id}/summary` and `.../summary/pdf`.

## Other screens

- Home: `GET home` returns sections `{status: "ok"|"error", data}`; render the ones that are ok.
- MedCard: `GET medcard`, then the section lists; `?updated_since=<ISO>` returns changes only; `GET medcard/export.pdf`.
- Pharmacy: `POST cart/items {medicine_id, quantity}` → `GET cart` (subtotal + 600 ₸ delivery) → `POST orders {payment_token}` → `GET orders/{id}/tracking`.
  Prescription items need `POST prescriptions/upload {file_id}` (upload with `purpose=prescription`) and a pharmacist's verification; until then the order is `pending_verification`.
- Questions: `POST inquiries {kind: "anonymous"|"intern"|"pharmacist", text}`; the answer shows in `GET inquiries/{id}`.
- Notifications: `GET notifications?type=all|appointments|updates`; badge from `GET notifications/unread-count`.

---

# Screen → endpoint map

| Screen (Figma) | Endpoints |
|---|---|
| Onboarding, Sign up | `auth/signup`, `legal/privacy-policy`, `meta` |
| Log in, Apple, Log out | `auth/login`, `auth/apple`, `auth/apple/link`, `auth/token/refresh`, `auth/logout`, `me/password` |
| Home | `home` |
| Emergency 103 (F1) | `emergency`, `emergency/taps`, `me/emergency-medical-info` |
| iBolit AI (F4) | `ai/conversations`, `ai/conversations/{id}/messages`, `ai/video-sessions` (mock) |
| Find your doctor, filters (F2, F8) | `specialties`, `doctors?q&specialty&visit_type&online_now&available_date&available_this_week&part_of_day&language&price_max&ordering&recommended_for`, `directory/stats` |
| Doctor profile, reviews (F8) | `doctors/{id}`, `doctors/{id}/reviews` GET/POST |
| Choose time, held, Confirm & pay (F2) | `providers/{id}/availability/days`, `.../slots`, `bookings/hold`, `bookings/{id}/confirm`, `payments/{id}/receipt` |
| Booking detail, cancel, reschedule | `bookings/{id}`, `/cancel`, `/reschedule`, `/calendar.ics`, `bookings/on-demand` |
| Services tab | `services/categories`, `services?q&category`, `services/{id}`; book via `bookings/hold` |
| Consultations (Upcoming / Past) | `consultations?tab=upcoming|past`, `consultations/{id}`, `/preparation` |
| Share records (consent) | `consents`, `consents/{id}/revoke`, `me/access-log` |
| Chat | `threads`, `threads/{id}/messages`, `threads/{id}/read`, `files` |
| Video consultation | `consultations/{id}/video/join|reconnect|events|end`, `request-video` |
| Consultation summary | `consultations/{id}/summary`, `/summary/pdf`, `/summary/versions`, `/summary/follow-up-reminder` |
| Medical Card (F3) | `medcard`, `medcard/timeline?kind=all|visits|labs|vaccines`, `medcard/allergies|medications|conditions|diagnoses|lab-results|vaccinations|documents`, `medcard/export.pdf`, `medcard/sync` |
| Smart reminders | `reminders?tab=today|upcoming|completed`, `reminders/{id}`, `reminders/{id}/complete`, `reminders/suggestions` |
| Articles | `articles/categories`, `articles?q&category`, `articles/picked`, `articles/{slug}` |
| Pharmacy | `medicines/categories`, `medicines`, `medicines/{id}`, `cart`, `cart/items`, `prescriptions`, `prescriptions/upload`, `orders`, `orders/{id}`, `/tracking`, `/cancel` |
| Ask anonymously / intern / pharmacist | `inquiries`, `inquiries/{id}`, `/follow-up`, `/save-to-medcard` |
| Notifications | `notifications`, `notifications/unread-count`, `notifications/read-all`, `notifications/{id}/read`, `me/notification-preferences` |
| Profile & settings | `me`, `me/address`, `me/emergency-contact`, `me/preferences`, `me/devices`, `me/legal/accept`, `me/data-export`, `support/messages` |
| Doctor app | `doctor/appointments`, `doctor/presence`, `doctor/availability/*`, `doctor/appointments/{id}/shared/{scope}`, `doctor/consultations/{id}/summary|sign|amend|complete|prescriptions`, `doctor/consultations/{id}/video-request/accept` |
| Staff (pharmacist, intern) | `staff/prescriptions`, `staff/prescriptions/{id}/verify`, `staff/inquiries`, `staff/inquiries/{id}/answer`, `orders/{id}/advance` (dev) |

---
