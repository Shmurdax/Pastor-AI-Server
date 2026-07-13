# Pastor-AI

## Why the UI can look "old"
Django does **not** serve Flutter source from `flutter_application_1/lib/`.
It serves the **pre-built web bundle** in `static/` (`index.html`, `main.dart.js`, etc.).

If you change Flutter code but skip a web rebuild + copy into `static/`,
`python manage.py runserver` will keep showing the previous UI.

## Refresh the UI after Flutter changes (Windows)
From `Pastor-AI-main`:

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
