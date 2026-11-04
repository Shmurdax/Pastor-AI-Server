---
name: ai-testing
description: >-
  Run AI testing for the pastor chat on christian-ai-test. Use when the user
  says "run AI testing", asks to run the pastor AI suite, or asks to test
  sermon notes, Bible study notes, topic switching, or reply accuracy.
---

# Run AI testing

Run the full pastor-chat suite. Do not stop after a smoke subset, and do not grade replies that the suite did not collect.

## Run

From the repository root:

```bash
python scripts/pastor_chat_suite.py
```

The suite signs in as `grokbot1@gmail.com` and posts every turn in `scripts/pastor_chat_cases.yaml` to the christian-ai-test chat API on one session. It writes `/tmp/pastor_chat_suite.json` unless `PASTOR_CHAT_SUITE_OUT` is set.

On this pod the script uses the local Django user and `http://127.0.0.1:8000`. From another machine set both `PASTOR_TEST_BASE_URL` and `PASTOR_TEST_TOKEN`. Do not invent either value, and do not print the token.

If the script says this checkout cannot reach the chat, put that error in the Cursor reply and stop. Do not invent scores.

## Deliver in chat

The command stdout is the scorecard. After the command finishes, paste that entire stdout into the Cursor reply. The reply is the delivery.

Include every turn. Keep each full answer, each accuracy score, each fail reason, the source titles, the passage titles, the unsupported sentences, and the scripture references that were not in the passages. Do not shorten an answer to its first lines. Do not drop passing turns. Do not replace the scorecard with a pointer to the JSON file.

Exit code 1 means at least one turn failed. Paste the full scorecard anyway. Anaphoric turns are expected to fail while the model sees only the latest prompt. Do not weaken a check to make the run pass, and do not change the chat pipeline unless the user asks for a product change.
