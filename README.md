This Pastor-AI-main folder should be able to run the AI and UI through Django and NGROK.

TIPS:
- Make sure Ngrok is downloaded and running via `ngrok http 8000`.
- Make sure Django is running via `python manage.py runserver`.
- After Flutter UI changes, rebuild and copy into `static/` (see `Pastor-AI-main/README.md` or run `Pastor-AI-main/deploy_flutter_web.ps1`).
- Double check file paths.
- Django, Ollama, and Ngrok should be the only things that need to be open.
- Use inspect (F12) on the webpage to help with troubleshooting errors.
