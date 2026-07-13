# Pastor-AI auth testing

## Important
By default the Flutter web build uses **mock login** (`USE_MOCK_AUTH=true`).
That means Sign in succeeds in the UI without calling Django.
To test the real login system, rebuild with `-UseRealApi`.

## A) Test the Django API (no Flutter needed)
Terminal 1:
```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server\Pastor-AI-main
python manage.py migrate
python manage.py runserver
```

Terminal 2:
```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server\Pastor-AI-main
.\test_auth.ps1
```

Expected: `API auth flow passed.`

Manual equivalent:
```powershell
# register
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/auth/register/ -ContentType application/json -Body '{"name":"Test User","email":"you@example.com","password":"Str0ngPass!"}'
# login
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/auth/login/ -ContentType application/json -Body '{"email":"you@example.com","password":"Str0ngPass!"}'
```

## B) Test login in the browser against Django
```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server\Pastor-AI-main
git pull
.\rebuild_web.ps1 -UseRealApi
python manage.py migrate
python manage.py runserver
```

Then:
1. Open http://127.0.0.1:8000/
2. Clear site data / hard refresh
3. Open Sign in
4. Create an account (Register) with email + password (8+ chars)
5. Log out, then log in with the same email/password
6. Confirm your name appears as signed-in

## C) Quick UI-only mock check (does not hit Django)
```powershell
.\rebuild_web.ps1
python manage.py runserver
```
Any email/password will "sign in" because mock auth is on.

## Notes
- Google Sign-In against a real backend needs `/api/auth/google/` (not implemented yet) plus `GOOGLE_CLIENT_ID`.
- Email/password register + login + me + logout are the supported real API path.
