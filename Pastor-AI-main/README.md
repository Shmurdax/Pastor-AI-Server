# Pastor-AI login setup

## Why any password worked
The Flutter UI was in **mock auth** mode. That is now off by default.
Rebuild and the app will call Django `/api/auth/*`.

## Full email/password login setup

```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server
git pull
cd Pastor-AI-main

python manage.py migrate
.\rebuild_web.ps1
python manage.py runserver
```

Confirm the rebuild printed:
`MODE: REAL Django auth`

Then in the browser:
1. Open http://127.0.0.1:8000/
2. F12 -> Application -> Clear site data
3. Ctrl+Shift+R
4. Open Sign in -> **Create one**
5. Register with name, email, password (8+ chars)
6. Confirm you are signed in
7. Sign out
8. Sign in again with the same email/password
9. Try a wrong password - it should fail
10. Try an unregistered email - it should fail

API-only check (optional):
```powershell
.\test_auth.ps1
```

## What is included
- Register -> creates Django user + token
- Login -> checks password, returns token
- Me / logout -> Bearer token auth
- Guest chat still allowed without login

## Not included yet
- Google Sign-In against Django (`/api/auth/google/` + `GOOGLE_CLIENT_ID`)
  The Google button is hidden until that is configured.
- Password reset / email verification

## Mock mode (demo only)
```powershell
.\rebuild_web.ps1 -UseMockAuth
```
