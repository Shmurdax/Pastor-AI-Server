# Pastor-AI

## Install Flutter (Windows) — required to rebuild the UI
If PowerShell says `flutter` is not recognized, the Flutter SDK is missing or not on PATH.

1. Download the Windows Flutter SDK zip: https://docs.flutter.dev/install/manual
2. Extract it somewhere simple with no spaces, e.g. `C:\src\flutter`
   (avoid `C:\Program Files\`)
3. Add Flutter to your user PATH in PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
  "Path",
  $env:Path + ";C:\src\flutter\bin",
  "User"
)
```

4. **Close that terminal and open a new PowerShell window**, then verify:

```powershell
flutter --version
flutter doctor
```

For web builds you mainly need Chrome/Edge available; Android Studio / Visual Studio are optional unless you also build mobile/desktop.

Official guide: https://docs.flutter.dev/install/manual

## Why the UI can look "old"
Django does **not** serve Flutter source from `flutter_application_1/lib/`.
It serves the **pre-built web bundle** in `static/` (`index.html`, `main.dart.js`, etc.).

If you change Flutter code but skip a web rebuild + copy into `static/`,
`python manage.py runserver` will keep showing the previous UI.

## Refresh the UI after Flutter changes (Windows)
From `Pastor-AI-main` (after `flutter` works in a **new** terminal):

```powershell
.\deploy_flutter_web.ps1
python manage.py runserver
```

Manual equivalent:

```powershell
cd flutter_application_1
flutter pub get
flutter build web --release --base-href /static/
# wipe and replace Django's static folder
Remove-Item -Recurse -Force ..\static\*
Copy-Item -Recurse -Force .\build\web\* ..\static\
cd ..
python manage.py runserver
```

Then hard-refresh the browser (`Ctrl+Shift+R`).
If it still looks cached: DevTools → Application → Service Workers → Unregister,
and clear site data for `localhost` / your ngrok URL.

## Python / AI packages
```
pip install langchain-core langchain-classic langchain-huggingface langchain-chroma langchain-ollama chromadb sentence-transformers
```

Make sure Ollama is running in the background.

## Tips
- Ngrok: `ngrok http 8000`
- Django: `python manage.py runserver`
- Use browser DevTools (F12) when troubleshooting API / UI issues.
