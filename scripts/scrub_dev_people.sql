-- Default pastoral redaction after a production copy lands on the dev pod.
UPDATE core_prayerrequest
SET name = 'Member', phone = '', prayer_text = '[redacted]', pastor_notes = '';
UPDATE core_userchathistory SET entries = '[]'::jsonb, active_session_id = '';
UPDATE core_responsereport SET user_query_snapshot = '', ai_response_snapshot = '', details = '';
