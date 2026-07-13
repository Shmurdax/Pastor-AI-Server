# Pastor-AI

## Install Flutter (Windows)
If `flutter --version` fails with "not recognized", Windows PATH does not include your SDK's `bin` folder. Having Flutter extracted under `C:\src\flutter` (or `C:\srs\flutter`) is enough — you do **not** need another copy.

### If Flutter is already in `C:\src\flutter`
```powershell
Test-Path C:\src\flutter\bin\flutter.bat
.\install_flutter_windows.ps1 -FlutterRoot "C:\src\flutter"
flutter --version
```

Or skip PATH and call it directly:

```powershell
& C:\src\flutter\bin\flutter.bat --version
.\deploy_flutter_web.ps1 -FlutterRoot "C:\src\flutter"
```

(`install_flutter_windows.ps1 -FlutterRoot ...` only adds that folder's `bin` to PATH; it will not re-download if the SDK is found.)

### If you do not have Flutter yet
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\install_flutter_windows.ps1 -InstallDir "C:\src"
flutter --version
```

## Why the UI can look "old"
Django does **not** serve Flutter source from `flutter_application_1/lib/`.
It serves the **pre-built web bundle** in `static/` (`index.html`, `main.dart.js`, etc.).

If you change Flutter code but skip a web rebuild + copy into `static/`,
`python manage.py runserver` will keep showing the previous UI.

## Refresh the UI after Flutter changes (Windows)
From `Pastor-AI-main`:

```powershell
.\deploy_flutter_web.ps1 -FlutterRoot "C:\src\flutter"
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
