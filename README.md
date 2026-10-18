# iBolit

Telehealth app for Kazakhstan: find verified doctors, book video or in-clinic visits, chat, video-call, keep a medical card and order medicine.

| Folder | What it is |
|---|---|
| [backend/](backend/) | Django REST API (Docker + PostgreSQL). Setup, demo accounts and the API guide are in [backend/README.md](backend/README.md) |
| `ios/` | iOS app (to be added) |

Quick start for the API:

```bash
cd backend
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_demo
```

Swagger: http://localhost:8000/api/docs
