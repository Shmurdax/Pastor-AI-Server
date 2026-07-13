# Pastor-AI — update the UI (follow exactly)

The old UI stays until `static\main.dart.js` is replaced by a **successful**
Flutter web build. Editing Dart files alone does not change what Django serves.

## Do this now

```powershell
cd C:\Users\damia\Source\Repos\Shmurdax\Pastor-AI-Server
git fetch origin
git checkout cursor/flutter-web-deploy-ui-0001
git pull
cd Pastor-AI-main

start ms-settings:developers
# Turn Developer Mode ON, then close and reopen PowerShell

.\rebuild_web.ps1
```

You must see **`SUCCESS — new UI is in static\`**.
If the script errors, the UI was NOT updated.

Verify the new UI is on disk:

```powershell
Select-String -Path .\static\main.dart.js -Pattern "LoginScreen" -SimpleMatch
```

If that prints nothing, rebuild failed / wrong files.

Then:

```powershell
python manage.py migrate
python manage.py runserver
```

In the browser:

1. Open http://127.0.0.1:8000/
2. F12 → Application → Service Workers → **Unregister**
3. Application → Storage → **Clear site data**
4. Ctrl+Shift+R

## Why it still looked old
- Your last `flutter build web` **failed**, so `static\` never got the new app
- Flutter service workers can keep serving the previous UI even after files change
- `rebuild_web.ps1` now builds with `--pwa-strategy=none` and checks that `LoginScreen` exists in `static\main.dart.js` before declaring success
