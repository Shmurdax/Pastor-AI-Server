# Pastor-AI

## Install Flutter (Windows)
If `flutter --version` fails with "not recognized", Flutter is not installed or not on PATH.

### Easiest fix
In PowerShell, from `Pastor-AI-main`:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\install_flutter_windows.ps1
flutter --version
```

That script downloads the stable Flutter SDK (if needed), adds `...\flutter\bin` to your User PATH, and refreshes the **current** terminal.

### Manual install
1. Install Git for Windows: https://git-scm.com/download/win
2. Download Flutter SDK: https://docs.flutter.dev/install/manual
3. Extract to `%USERPROFILE%\develop\flutter` (example final file: `...\flutter\bin\flutter.bat`)
4. Add **`...\flutter\bin`** (not the parent folder) to User PATH, then open a **new** PowerShell

Check whether the SDK files exist:

```powershell
Test-Path "$env:USERPROFILE\develop\flutter\bin\flutter.bat"
Get-ChildItem "$env:USERPROFILE\develop\flutter\bin\flutter.bat" -ErrorAction SilentlyContinue
```

If that returns `False`, Flutter was never extracted to that folder.

## Why the UI can look "old"
Django does **not** serve Flutter source from `flutter_application_1/lib/`.
It serves the **pre-built web bundle** in `static/` (`index.html`, `main.dart.js`, etc.).

If you change Flutter code but skip a web rebuild + copy into `static/`,
`python manage.py runserver` will keep showing the previous UI.

## Refresh the UI after Flutter changes (Windows)
From `Pastor-AI-main` (after `flutter --version` works):

```powershell
.\deploy_flutter_web.ps1
python manage.py runserver
```

If Flutter exists but still is not on PATH:

```powershell
.\deploy_flutter_web.ps1 -FlutterRoot "$env:USERPROFILE\develop\flutter"
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
