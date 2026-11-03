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

If the script says this checkout cannot reach the chat, stop. Report that the suite has to run on christian-ai-test. Do not invent scores.

## Report

Read the JSON report and tell the user:

- How many turns passed and how many failed.
- The accuracy score for every turn, including the ones that passed.
- For each failure, the turn id, the reasons, and the first lines of the answer.
- The unsupported sentences and scripture references that were not in the retrieved passages.

The suite exits 1 when any turn fails. Anaphoric turns are expected to fail while the model sees only the latest prompt. Report that result. Do not weaken a check to make the run pass, and do not change the chat pipeline unless the user asks for a product change.
