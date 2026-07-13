# Pastor-AI — do these steps in order

## 0) Enable Windows Developer Mode (required once)
```powershell
start ms-settings:developers
```
Turn **Developer Mode** ON, then reopen PowerShell.

## 1) Pull the latest fix (missing Flutter packages + rebuild script)
In a new PowerShell:

```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server
git fetch origin
git checkout cursor/flutter-web-deploy-ui-0001
git pull
cd Pastor-AI-main
```

## 2) Rebuild the web UI into Django's static folder
```powershell
.\rebuild_web.ps1
```

That script uses `C:\src\flutter\flutter\bin\flutter.bat` automatically.

## 3) Start Django
```powershell
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ and press **Ctrl+Shift+R**.

---

### What went wrong in your last attempt
1. `pubspec.yaml` was missing packages (`provider`, `shared_preferences`, `flutter_secure_storage`, `google_sign_in`) — build failed.
2. Because the build failed, wiping `static\` left the site half-broken (404s).
3. `deploy_flutter_web.ps1` was not on your local branch yet.
4. `flutter` on PATH is optional; the rebuild script calls the bat file directly.

### Manual rebuild (if you prefer not to use the script)
```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server\Pastor-AI-main\flutter_application_1
& C:\src\flutter\flutter\bin\flutter.bat pub get
& C:\src\flutter\flutter\bin\flutter.bat build web --release --base-href /static/ --no-wasm-dry-run
Remove-Item -Recurse -Force ..\static\*
Copy-Item -Recurse -Force .\build\web\* ..\static\
cd ..
python manage.py migrate
python manage.py runserver
```

Run **one command at a time**. Do not paste the whole block as one `>>` continued command until the build succeeds.
