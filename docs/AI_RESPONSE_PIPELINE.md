# How Nordin's AI Builds a Reply

This is a learning map of **every code path that currently influences what the chat model says** on the `development` branch (commit `28d007e` and later merges onto that line).

It is written so you can sit with the repo, open a file named here, and see what that file does to the answer. It covers:

1. The **base LLM** and the **Christian LoRA**
2. The **base documents** (PDFs, videos, websites, NKJV) and how they are cleaned, chunked, embedded, and stored
3. How **RAG** is searched, mixed, and formatted into `REFERENCE NOTES`
4. **Every loop** a request goes through before the user sees a final answer
5. Code that **exists in the repo but does not currently change the live reply** (so you are not misled)

If a file, function, or loop is not listed here, it does not steer generation on this branch. Billing, prayer forms, events, and the sermon PDF viewer affect *who can chat* or *what they can open after the fact*. They do not write the answer.

---

## 1. How to read this document

Read **Section 2** once so the three layers of “the AI” are clear.

Then use **Section 3** as the table of contents for the live request. Each numbered loop is explained later with the exact file and the role of the code.

When you want the “why did it say *that*?” answer for a real chat, walk the loops in order:

1. What did the user type, in which language, in which session?
2. Did the scope gate refuse it?
3. What English search queries were embedded?
4. Which Qdrant chunks survived the filters?
5. How were those chunks formatted as notes and teaching claims?
6. What system prompt + history + human message reached vLLM?
7. Did a retry, continuation, or claim-repair pass append more text?
8. Was the English draft translated for display?

---

## 2. The three layers of “the AI”

The product answer is **not** a single model call. It is three stacked influences:

| Layer | What it is | Where it lives | What it does to the reply |
| --- | --- | --- | --- |
| **Base LLM** | `Qwen/Qwen2.5-14B-Instruct-AWQ` | Hugging Face, loaded by vLLM | General English (and some other languages), instruction following, pastoral prose style from Qwen Instruct |
| **Christian LoRA** | `apophaticai/qwen2.5-14b-christianai-v1`, served as model id `christianai` | Private HF repo; adapter rank 16 | Shifts word choice and Christian framing toward this ministry’s fine-tune. It does **not** contain the sermon library |
| **RAG + prompts** | Django retrieval + system prompt + history | This repo | Supplies Pastor Don/Susan notes, NKJV wording, identity, scope, required teaching points, and sampling settings |

If RAG is empty, the LoRA still writes *something*. That is why empty notes must be replaced with an explicit “do not invent quotations” sentinel. If RAG is full of mixed sermons, the base model will try to mash them into one outline. The prompt can only *ask* it not to; sampling is still stochastic.

**Thumbs / reports / DPO / KTO do not live-update this model.** `ResponseReport` is a staff inbox. Votes are not training data in this pipeline.

---

## 3. Master map: every loop from tap to final answer

This is the live path for a Premium member sending a chat message. Loops marked **offline** run when staff ingest documents, not on every chat.

```
                    OFFLINE (staff ingest)
  PDF/DOCX / video / website / NKJV
           │
           ▼
  [L0] extract → clean → chunk → embed (BGE) → upsert Qdrant sermon_brain
           │
           └──── vectors sit in Qdrant until a chat asks for them ────┐
                                                                      │
                    ONLINE (one user message)                         │
  Flutter composer (max 1000 chars)                                   │
           │                                                          │
           ▼                                                          │
  [L1] HTTP POST /api/chat/  (auth, premium, session hash)            │
           │                                                          │
           ▼                                                          │
  [L2] Language: non-English question → English (separate LLM call)   │
           │                                                          │
           ▼                                                          │
  [L3] Scope gate (regex allow, else YES/NO LLM). NO → decline reply  │
           │ YES                                                      │
           ▼                                                          │
  [L4] Load last ≤10 ChatMessage turns for this scoped session        │
           │                                                          │
           ▼                                                          │
  [L5] Greeting? skip Qdrant. Else expand search queries              │
           │                                                          │
           ▼                                                          │
  [L6] For each query: embed → Qdrant cosine search (k = 24×8)   <────┘
           │
           ▼
  [L7] Merge hits → lexical topic filter → similarity threshold
           │
           ▼
  [L8] Diversity pick (notes / video / Bible, max per source)
           │
           ▼
  [L9] Library-pull? keep one sermon. Then NKJV verse payload lookup
           │
           ▼
  [L10] Format REFERENCE NOTES + extract required teaching claims
           │
           ▼
  [L11] Build system prompt + history + human message
           │
           ▼
  [L12] Token-budget trim loop (notes, optional blocks, history, max_tokens)
           │
           ▼
  [L13] Generate loop 1: stream tokens from vLLM (Qwen+LoRA)
           │ empty / timeout?
           ▼
  [L14] Retry loop: warmup GPU, 90s timeout, then smaller prompt
           │
           ▼
  [L15] Expansion loop (at most 1): continue if cut off or too short
           │
           ▼
  [L16] Claim-repair loop: if required points missing, continue with steer
           │
           ▼
  [L17] Save English answer → translate for UI language → cite 3–5 sources
           │
           ▼
  [L18] SSE deltas to Flutter → live bubble → done event
```

That is the whole product path. The rest of this document is each box, with the code that implements it.

---

## 4. Layer A — base LLM, LoRA, and sampling

### 4.1 What vLLM actually loads

Local GPU (`start.sh`):

- Base weights: `CHRISTIANAI_BASE_VLLM` default `Qwen/Qwen2.5-14B-Instruct-AWQ`
- LoRA folder: `CHRISTIANAI_LORA_DIR` default `/workspace/pastor-ai/christianai-lora`
- Served name: `VLLM_MODEL` / `CHRISTIANAI_SERVED_NAME` default `christianai`
- Flags when the adapter file exists: `--enable-lora --lora-modules christianai=<lora_dir> --max-lora-rank 16`
- Context: `--max-model-len` from `VLLM_MAX_MODEL_LEN` (default 32768)

If the LoRA file is missing, `start.sh` **falls back to the base model id only**. Chat still works, but without the Christian adapter.

Serverless GPU (`serverless/vllm.env.example`):

```
MODEL_NAME=Qwen/Qwen2.5-14B-Instruct-AWQ
ENABLE_LORA=true
MAX_LORA_RANK=16
LORA_MODULES={"name":"christianai","path":"apophaticai/qwen2.5-14b-christianai-v1"}
OPENAI_SERVED_MODEL_NAME_OVERRIDE=christianai
QUANTIZATION=awq
MAX_MODEL_LEN=32768
```

Django never talks to Hugging Face at chat time. It talks to an OpenAI-compatible `/v1/chat/completions` server. vLLM applies the **Qwen2.5 Instruct chat template** (special tokens around system / user / assistant). That template is *inside the model card / tokenizer*, not in this repo. Changing the Django system prompt still goes through that template.

### 4.2 How Django points at the worker — `backend/app/core/chat_llm.py`

| Symbol | Role in the reply |
| --- | --- |
| `CHAT_TEMPERATURE = 0.7` | Official Qwen Instruct temperature. Higher = more paraphrase / mash-up risk |
| `CHAT_TOP_P = 0.8` | Nucleus sampling |
| `CHAT_VLLM_EXTRA_BODY = {repetition_penalty: 1.05, top_k: 20}` | Qwen Instruct defaults. Stops some loops without OpenAI frequency penalty |
| `CHAT_PRESENCE_PENALTY = 0` / `CHAT_FREQUENCY_PENALTY = 0` | Left at 0 on purpose. OpenAI-style penalties made unused **Chinese** tokens cheap on this bilingual model |
| `resolve_vllm_url` | `RUNPOD_VLLM_ENDPOINT_ID` wins, else `VLLM_URL`, else `http://vllm:8000/v1` |
| `resolve_vllm_model` | Model id sent to the API (`christianai`) so the LoRA module is selected |
| `resolve_vllm_api_key` | Bearer token for serverless; `"not-needed"` only for local vLLM |
| `_live_vllm_api_key` | Re-reads `config.env` / `tokens.env` per request because RunPod CPU images can zero `environ` |
| `get_chat_llm` | Builds LangChain `ChatOpenAI` with those sampling fields, `max_tokens`, timeout, 1–2 HTTP retries |
| `estimate_chat_tokens` | Pessimistic `len*2/5` estimator used to keep prompt+completion inside the window |
| `fit_chat_budget` | **Loop L12.** Trims prompt so generation cannot overflow `CHAT_CONTEXT_WINDOW` capped by `VLLM_MAX_MODEL_LEN` |
| `NOTES_MARKER` / `EMPTY_REFERENCE_NOTES` | The notes block is the last part of the system prompt. Empty notes become an explicit “do not invent quotations” paragraph, never the old `"No relevant sermon notes found."` one-liner |

`get_chat_llm` is also used for the **scope gate**, **out-of-scope decline**, **translation**, and **video topic metadata**. Those are extra LLM loops, not the pastoral answer, but they still change what the user sees (refuse vs teach; Spanish vs English; how videos are indexed).

### 4.3 Worker wake-up — `backend/app/core/vllm_warmup.py`

`warmup_vllm_worker` GETs `{base_url}/models`. RunPod Serverless boots a GPU on the first request. Flutter calls `/api/chat/warmup/` while the user is browsing (`frontend/lib/main.dart` → `_apiService.warmupChat()`). On an empty stream, chat generation calls the same warmup with `force=True` before retrying.

This does not change *wording*. It changes whether tokens arrive at all.

### 4.4 Env overlay — `backend/app/pastor_ai/workspace_env.py`

RunPod CPU containers can wipe process environment. `load_workspace_env` re-reads `config.env` then `tokens.env` on each LLM client build. File values win for `VLLM_URL`, `RUNPOD_VLLM_ENDPOINT_ID`, `CPU_ONLY`, and secrets. If this overlay is wrong, chat 401s or talks to the wrong endpoint. Flutter maps many HTTP failures to “Could not connect.”

### 4.5 Deployed retrieval defaults — `vllm_runtime.sh`

`vllm_apply_config` writes chat/retrieval knobs into `config.env` on start. Important mismatch:

| Knob | Python default in `views.py` | Written by `vllm_runtime.sh` / `config.env.example` |
| --- | --- | --- |
| `RETRIEVAL_THRESHOLD` | `0.72` | `0.8` |
| `RETRIEVAL_MAX_PER_SOURCE` | `2` | `4` |
| `CHAT_MAX_TOKENS` | `1024` | `1024` |
| `INGEST_CHUNK_SIZE` | quote splitter default `550` | `1800` on deployed config |

On a pod that has been through `start.sh`, **the env file wins**. Weak sermon matches drop more aggressively at 0.8 than at 0.72.

---

## 5. Layer B — base documents: offline ingest loops (L0)

Nothing can be retrieved that was not ingested. There are four ingest fronts. All of them end in the same Qdrant collection `sermon_brain` (768-d cosine, BGE embeddings).

### 5.1 Shared embedding model — `backend/app/core/embeddings_utils.py`

- Model: `EMBEDDING_MODEL_NAME` default `BAAI/bge-base-en-v1.5`
- Device: CPU by default (`EMBEDDING_DEVICE=cpu`, CUDA hidden) so embeddings cannot OOM the GPU that vLLM owns
- `normalize_embeddings: True` — required for cosine similarity in Qdrant
- Process-wide singleton `get_embeddings()`

**Chat search and ingest must use the same model.** If someone re-embeds with a different model, retrieval scores become noise.

### 5.2 Qdrant collection — `backend/app/core/qdrant_utils.py`

| Function | Role |
| --- | --- |
| `get_qdrant_url` / `get_collection_name` | Default `http://qdrant:6333`, collection `sermon_brain` |
| `ensure_sermon_collection` | Creates empty 768-d cosine collection if the volume was wiped |
| `ensure_payload_indexes` | Keyword/int indexes on `chunk_kind`, `book`, `file_hash`, `source`, `chapter`, `verse_start`, `verse_end` so NKJV lookup is a filter, not a scan |

Each Qdrant point payload looks like:

```
id: uuid5(chunk_hash)
vector: 768 floats, unit-length
payload:
  text: <chunk body the model will see>
  source, title, file_hash, chunk_hash, position
  chunk_kind, quote_text, ... per-type fields
  metadata: { nested copy of the same fields }
```

LangChain `QdrantVectorStore` is constructed in chat with `content_payload_key="text"` and `metadata_payload_key="metadata"`. Retrieval therefore reads **`text` as the chunk** and **`metadata.*` as labels**.

### 5.3 Postgres catalog — `backend/app/core/models.py`

These tables do not generate wording, but they decide *which* files exist and *which* past turns are memory:

| Model | Role in the reply |
| --- | --- |
| `IngestedDocument` | Title, `source_kind` (document/video/website), `file_hash`, `topic_metadata`, `view_only`. Chat source labels prefer this title over the raw filename |
| `IngestedChunk` | Maps chunk hashes to Qdrant point ids; used to skip duplicate upserts |
| `ChatMessage` | **The only conversation memory the generator reads.** `session_id` + `user_query` + `ai_response` |
| `UserChatHistory` | Flutter sidebar backup. **Not** fed into the LLM |
| `ResponseReport` | Staff thumbs/reports. **Not** fed into the LLM |
| `IngestionJob*` | Progress/logging for staff ingest |

### 5.4 PDF / DOCX sermon notes — `ingestion_service.ingest_uploaded_files`

Loop per uploaded file:

1. Accept `.pdf` or `.docx` only.
2. Optional replace-existing by filename.
3. SHA-256 the bytes. Skip near-duplicates by file hash, cleaned-text hash, or normalized title (`document_titles.normalize_title_key`).
4. Store the PDF on disk (DOCX is converted). The **PDF on disk is never cleaned**. Library links serve the original.
5. Extract text (`pypdf`).
6. **Clean extracted text only** (`document_cleanup.clean_extracted_document`): strip headers/footers/page numbers, fix hyphenation, join wrapped lines, drop copyright boilerplate, dedupe short lines.
7. Wrap as markdown `# {prettified title}\n\n{body}`.
8. Split:
   - If the filename matches Bible markers (`bible`, `nkjv`, …) → verse-level NKJV chunks (`bible_chunking.split_nkjv_document`).
   - Else → quote-sized sermon windows (`quote_chunking.split_sermon_quote_chunks`).
9. Embed all chunk strings with BGE.
10. Upsert points; skip chunks whose text hash already exists.

**Why this changes answers:** cleanup removes TOC junk that would otherwise become high-similarity “hits.” Quote-sized windows mean a retrieved note is a handful of sentences, not a whole PDF. The stored `quote_text` field is later mined for **required teaching points**.

### 5.5 Quote-level sermon split — `backend/app/core/quote_chunking.py`

| Function | Role |
| --- | --- |
| `split_sermon_quote_chunks` | Pack paragraphs into windows of `INGEST_CHUNK_SIZE` (code default 550, deployed often 1800) with `INGEST_CHUNK_OVERLAP` (code 80, deployed 250) |
| `extract_quote_spans` | Quoted strings plus sentence-sized lines stored as `quote_text` joined by ` \| ` |
| `spoken_text_without_timestamps` | Strips `[mm:ss–mm:ss]` prefixes so claims/quotes are spoken words, not timestamps |

Each sermon chunk metadata:

```
chunk_kind: "sermon_quote"
quote_text: "first distinctive sentence | second | …"   # up to 4, max 1200 chars
```

### 5.6 NKJV verse split — `bible_chunking.py` + `bible_refs.py`

| Function | Role |
| --- | --- |
| `parse_nkjv_verses` | Parses book headers, `chapter:verse` lines, packed verses |
| `pack_nkjv_verse_chunks` | Groups `BIBLE_VERSES_PER_CHUNK` (default 4) verses into one embedding window |
| `canonical_book_key` / `format_verse_ref` | Stable keys so chat can look up `John 3:16` by payload filter, not by hoping cosine search found it |

Chunk body looks like:

```
# John 3

16 For God so loved the world...
17 For God did not send His Son...
```

Metadata:

```
chunk_kind: bible_verse
content_type: bible
book, chapter, verse_start, verse_end, verse_ref
quote_text: concatenated verse wording
```

If the verse parse is weak (`< 8` verses trusted), ingest falls back to `bible_passage` character splits. Those are harder to look up exactly later.

### 5.7 Video / audio — `video_ingestion.py` + Whisper + topic metadata

Loop per media file:

1. `whisper_transcribe.transcribe_video_file` (local faster-whisper or serverless Whisper endpoint). Language hint from `WHISPER_LANGUAGE` if set.
2. `transcript_normalize.normalize_transcript_segments`: strip fillers, drop ads/CTAs, drop isolated off-topic lines. **Timestamps stay on surviving lines.**
3. `video_topic_metadata.build_video_topic_metadata`:
   - Heuristic keywords/summary from the transcript
   - Optional **extra LLM call** (`VIDEO_TOPIC_METADATA_LLM=1`) asking vLLM for JSON `{topic_title, topics, keywords, summary, scripture_refs, speakers}`
4. `format_searchable_header` is **prepended to every embedded chunk**. Embeddings only see text, so without this header a date-titled video is almost unfindable.
5. Timestamped lines packed into ~chunk_size groups with 1-segment overlap.
6. First chunk is often `video_topic_overview` (header + “this overview indexes the full video…”).
7. Remaining chunks `video_transcript` with `timestamp`, `start_s`, `end_s`, `quote_text`.

Embedded video chunk text looks like:

```
# Faith That Works
Date/source label: 2026-05-23
Topics: faith, measure of faith
Keywords: ...
Scripture: Romans 12:3
Speakers: Don Nordin
Summary: ...
Search phrases: Faith That Works, faith, ...

[12:04–12:31] You have been given THE measure of faith...
[12:31–12:58] ...
```

Chat may mention that time range because the system prompt allows citing labeled video times and forbids inventing them.

**Whisper misspellings** (Cain→Kane, Abel→Able) are why retrieval later has alias maps. Bad transcripts become bad answers.

### 5.8 Website crawl — `website_crawl/`

`run_website_crawl_and_ingest`:

1. Crawl allowlisted ministry domains (`website_crawl/config.py`: thenordins.org, myct.church, …).
2. HTML → markdown (`extract.py`): drop nav/footer/script, classify `content_type` (teaching_media, church_info, …).
3. Ingest markdown via `ingest_markdown_documents` (lighter cleanup, same quote splitter).
4. Linked public PDFs go through the same PDF ingest path.

Website chunks are more “ministry page” than “sermon thesis.” Diversity padding can pull them into a pastoral answer if they score high. That is a common source of contact-page or event tangents.

### 5.9 Legacy CLI — `backend/app/ingest_qdrant.py`

Older markdown-directory loader. **Not** what Django admin uses. Do not assume live Qdrant was built this way. The live path is `ingestion_service.py`.

### 5.10 Titles — `document_titles.py`

`prettify_title` turns `FAITH_LIFT.PDF` into a human title. That title is stored on the document **and** in Qdrant `title`. Source chips in the UI and `[Note N | Title]` labels in RAG both use it. Changing a title in admin changes how the model *names* the source, not the body text, unless you re-ingest.

---

## 6. Layer C — one live chat request (L1–L18)

### 6.1 Frontend: what is sent — `frontend/lib/`

| File | Role |
| --- | --- |
| `chat_input_limits.dart` | Caps the composer at **1000 graphemes**. Longer pastoral asks never leave the phone |
| `main.dart` `_sendMessage` / `_submitMessage` | Sends `query`, Flutter `sessionId`, `regenerate`, `language`, `stream: true` |
| `services/api_client.dart` `chatStream` | `POST /api/chat/` with `Authorization: Token …`, `Accept: text/event-stream` |
| `main.dart` warmup | `POST /api/chat/warmup/` so the GPU is already booting |
| `chat_stream.dart` | Parses SSE `data:` blocks; paints `delta` into one live AI bubble; `done` writes `answer`, `sources`, `message_id` |
| `chat_history_merge.dart` | Merges sidebar backups. **Does not** send history to the model |
| `l10n/app_locale.dart` | UI language code (`en/es/fr/pt/de/ko/zh`) becomes the `language` field |

The client does **not** send prior turns. The server reloads them from `ChatMessage` using a **hashed session id**.

### 6.2 Routing, auth, premium — L1

`pastor_ai/urls.py` maps `/api/chat/` and legacy `/chat/` to `ChatAPIView`.

`ChatAPIView`:

- `TokenAuthentication` only (session cookies would CSRF Flutter)
- `IsAuthenticated` + `HasPremiumAccess` (`api/permissions.py`) — unpaid users never reach generation
- Optional `PUBLIC_API_KEY` via `X-API-Key`
- GET returns 404 on purpose so browsers cannot poke the endpoint

`_scoped_session_id` hashes `user_id|flutter_uuid` (or User-Agent for guests) with `SESSION_SCOPE_SALT`. Two accounts with the same Flutter UUID do not share memory. IP is not used, so mobile IP churn does not orphan history.

`regenerate=true` rewrites the latest matching `ChatMessage` instead of inserting a new row, and **excludes that row from history** so the model does not see the answer it is replacing.

### 6.3 Language inbound — L2 — `chat_language.py` + `chat_translate.py`

`normalize_chat_language` maps locale strings to `en/es/fr/pt/de/ko/zh`.

If the UI language is not English, `english_search_query` makes a **separate LLM call** (`temperature=0.2`) with:

> Translate this user question into English. Return only the English question.

All retrieval and generation then use that English string. The original language is kept in the database as `user_query`. A bad translation (losing “measure of faith”, etc.) sends Qdrant to the wrong neighborhood.

Generation itself is instructed to write **English**. Display translation happens after save (L17).

### 6.4 Scope gate — L3 — `scope_gate.py`

This is the first **generation loop**, but it is not the pastoral answer.

1. If `CHAT_SCOPE_GATE` is off → allow.
2. If the English query matches `_ALWAYS_IN_SCOPE_PATTERNS` (marriage, bible, abortion, church, …) → allow without an LLM call.
3. Else call the same `christianai` model with a **YES/NO-only** system prompt, `temperature=0.0`, `max_tokens=6`.
4. `parse_scope_gate_response`: first token YES/NO. Unclear or error → **allow** (fail open).
5. If NO: `generate_out_of_scope_reply` is a **second** LLM call (`temperature=0.7`, `max_tokens=220`) that writes a short decline. That text is saved and streamed as the whole answer. **No RAG.**

The gate prompt is deliberately permissive. Format words like “essay” or “outline” are not enough to refuse. Jailbreaks and purely secular busywork are the intended NOs.

### 6.5 History load — L4 — `views.py` + `ChatMessage`

Newest `MAX_HISTORY_TURNS` (default 10) rows for this scoped session, then rebuilt oldest-first until `MAX_HISTORY_CHARS` (20000).

From those rows the pipeline also extracts:

- `prior_user_queries` — used to keep follow-up search on-topic
- `prior_ai_texts` — used to extract already-used quotes/verses (novelty penalty) and headings (search expand)
- `used_quotes` / `used_verses` — down-rank chunks the model already quoted in this thread

**On this `development` snapshot, follow-up search still anchors to the last prior user line**, not the whole thread. `topic_anchor_query` is `{last_prior} {current}`. `expand_search_queries` puts `prior_focus` first so “expand week one” still searches the previous topic. A later unmerged experiment searched *all* user asks; that is **not** this document’s live path.

History messages are full user+AI text, not summaries. Long prior essays crowd the window and can make the model reprint an outline. `fit_chat_budget` will drop oldest pairs if needed, but tries to keep at least 5 exchanges (`_MIN_KEEP_HISTORY_MESSAGES = 10` messages).

### 6.6 Greeting short-circuit — L5

`looks_like_brief_social` (`chat_system_prompt.py`) is a regex for hi/thanks/how-are-you. Those turns:

- Skip Qdrant entirely (`docs = []`, empty context)
- Prefix the human message with `CONVERSATIONAL_STEER` (“one short warm paragraph, do not quote sermons”)

Without this, a “hello” still retrieves random high-similarity intros and the model dumps timestamps.

### 6.7 Search-query expansion — L5/L6 — `expand_search_queries`

Up to 7 (chat calls `limit=7`) distinct strings are embedded. Order matters because later filters still prefer high cosine scores.

Typical follow-up set:

1. Keyword core of the **previous** user question (`prior_focus`)
2. `Pastor Don Nordin {prior_focus}`
3. `{prior_focus} {headings from prior AI replies}`
4. `{prior_focus} {current focus}`
5. Bible names / Genesis 4-style landing passages when names are detected
6. Current focus + `Pastor Don Nordin {focus}` when it is a new topic

`keyword_search_query` strips instruction filler (`generate`, `sermon`, `outline`, `explain`, …) so the embedding is *homosexuality* or *faith*, not *write a sermon about*.

`retrieval_bible_names` uses `data/bible_names.txt` (thousands of names) minus a denylist of group words (`israel`, `church`, `gospel`, …) so “John” can be a person, but “the church” is not treated as a character search.

Hard-coded story landings (`_NAME_PASSAGES`): Cain/Abel → Genesis 4, Noah → Genesis 6, etc. Those strings are extra search queries, then NKJV lookup can fetch the exact verses.

`looks_like_library_pull` (`pull up a sermon`, `from the sermon library`, `excerpt from…`) strips words like `library`/`excerpt` from the focus so they do not match every PDF.

### 6.8 Qdrant search loop — L6 — `search_queries_on_store`

For **each** expanded query:

```
vectorstore.similarity_search_with_score(query, k=RETRIEVAL_K * RETRIEVAL_CANDIDATE_MULTIPLIER)
```

Defaults: `k = 24 * 8 = 192` candidates per query. Several queries → hundreds of hits, then `merge_scored_hits` keeps the **best score per chunk fingerprint** (first 400 lowercased characters).

BGE + cosine: **higher score is better**, typically ~0.5–0.95. This is not a percent-correct; it is vector similarity.

### 6.9 Lexical topic filter — L7 — `filter_hits_by_topic`

Cosine search loves generic sermon intros (“today we are able to…”). For a named-entity question (Cain, Abel), this filter **drops chunks that do not mention those names** (with Whisper aliases: Abel↔able only if Cain is also in the chunk, so ordinary “we are able” intros die).

If *no* chunk names the people, it keeps **Bible chunks only**, not random PDFs.

For ordinary topics (marriage, faith), it prefers overlap with `query_focus_tokens` but will pad back up to `max(6, retrieval_k)` from the ranked list if too few overlap.

`topic_overlap_score` also searches `topic_title`, `title`, `keywords`, `scripture_refs` in metadata — that is why the video searchable header exists.

### 6.10 Similarity threshold — L7 — `apply_retrieval_threshold`

If enough hits clear `RETRIEVAL_THRESHOLD` (0.72 in code, often **0.8 on the pod**), weaker hits are discarded. Soft escape: tiny already-filtered sets (true Cain/Abel clips at 0.74) are **not** thrown away just because a generic intro scored 0.93.

This is why a slightly-wrong embedding can yield *zero* useful notes even though the PDF is in Qdrant.

### 6.11 Diversity selection — L8 — `select_diverse_docs`

Picks `RETRIEVAL_K` (24) chunks with an MMR-style score:

```
value = 0.72 * cosine
        - 0.28 * Jaccard overlap with already picked chunks
        - novelty_penalty (already quoted in this chat)
        - 0.14 * times this source was already picked
        + 0.40 * lexical topic overlap
```

Slot mix (defaults):

- ~40% Bible (`RETRIEVAL_BIBLE_RATIO`)
- remaining sermon slots split ~45% video / rest written notes when both exist
- `RETRIEVAL_MAX_PER_SOURCE` (2 in code, 4 on many pods)
- `RETRIEVAL_MAX_PER_BIBLE_BOOK` (2)

Fill order: written notes → video → leftover sermons → Bible → anything.

**This mix is why a marriage question can still include an unrelated wine/gifts clip:** diversity *pads* extra sources even when one sermon already answered the question. The model then treats every `[Note N]` as equally obligatory.

Novelty penalty (`_novelty_penalty`) down-ranks chunks whose text already appeared as a quotation or verse in prior AI replies, so follow-ups are pushed toward unused lines.

### 6.12 Library-pull lock — L9 — `restrict_docs_to_primary_source`

Only when `looks_like_library_pull(query)` is true. Keeps chunks from **one** non-Bible source (the one with most topic-token overlap) plus up to 2 Bible docs.

“Give me a three-point sermon on faith” is **not** a library pull. That regex requires pull-up / library / excerpt wording. Those asks still get the 3–5 source mix.

`LIBRARY_PULL_STEER` is also appended to the system prompt in that case: stay inside the single retrieved sermon; do not change what an illustration teaches.

### 6.13 Exact NKJV lookup — L9 — `grounding.lookup_nkjv_verses`

`verse_refs_for_lookup` parses book/chapter/verse from the **topic query and retrieved chunk text**.

Then Qdrant `scroll` with payload filters:

```
chunk_kind = bible_verse
book = john
chapter = 3
verse_start ≤ 16 ≤ verse_end
```

Those exact wording chunks are appended if not already present. This is how the model is *supposed* to get NKJV text instead of quoting from Qwen memory.

`verify_answer_grounding` / `grounded_fallback_answer` / `GROUNDING_REPAIR_STEER` exist in `grounding.py` and are **not called from `ChatAPIView`**. They are test-only on this branch. Invented verses are not currently auto-rewritten.

### 6.14 Format REFERENCE NOTES — L10 — `format_reference_notes`

This is the RAG block the model sees. Each kept chunk becomes:

```
[Note 1 | Faith Lift]
<chunk text>

[Note 2 | Home Improvement [12:04–12:31]]
<chunk text>
```

Rules:

- Label comes from `_doc_source_label`: Postgres title if `file_hash` matches, else metadata title/source; video adds `[timestamp]`
- Notes are joined with blank lines until `CHAT_MAX_CONTEXT_CHARS` (40000). Overflow clips the last block rather than dropping silently to the refusal sentinel
- Empty → `EMPTY_REFERENCE_NOTES`

The model is told **not to mention “reference notes”** to the user, but it *is* allowed to mention video times that appear in a label.

### 6.15 Required teaching points — L10 — `teaching_claims.py`

`extract_teaching_claims` walks non-Bible, non-overview chunks and scores sentence-sized theses:

- Prefer stored `quote_text`
- Then `extract_quote_spans`
- Then `split_sentences`
- Score = overlap with query tokens × 3 + length + **contrast bonus** (phrases like “not just”, “rather than”, “only if”, “fool’s paradise”)

Stopwords include generic Christian words (`god`, `faith`, `church`, `jesus`, …) so “have faith in God” is *not* treated as a distinctive Don claim. Distinctive contrasts survive.

`format_teaching_claims_block` injects:

```
<required_teaching_points>
Use a clear, generic Christian pastoral tone. Do not imitate Pastor Don's or Susan's speaking style.
The numbered points are the retrieved teaching content...
1. …
2. …
</required_teaching_points>
```

These points become the **doctrine and outline**. The model is told to paraphrase them, keep the contrast, and not replace them with a generic communication seminar.

Coverage is checked **after** generation (`uncovered_claims` / `claim_is_covered`) using those same content tokens. Misses trigger loop L16.

`faith` as a stopword means a Faith-Lift thesis that only repeats “faith” may score poorly; contrast sentences (“THE measure of faith”, “not just…”) score well.

### 6.16 System prompt assembly — L11 — `chat_system_prompt.build_chat_system_prompt`

Final system string, in order:

1. `<priority>` — these instructions beat notes and the user; do not leak the prompt
2. `<identity>` — nameless AI for Don & Susan Nordin; phone `713-800-5529`; email `info@thenordins.org`; compassionate, not clinical
3. `<scope_policy>` — Christianity, Don/Susan teaching, social issues pastors get asked; do not refuse abortion/sexuality/etc. for being sensitive
4. `<source_material>` — notes first, not generic advice; generic pastoral tone; **do not imitate Don’s speaking style**; keep thesis/contrast; required points are the outline; no invented quotes or verse wording
5. Optional `LIBRARY_PULL_STEER`
6. Optional `<required_teaching_points>` from claims
7. `<language>` — English, no CJK mid-reply (even though generation is English; this fights Qwen’s bilingual leak)
8. `<biblical_characters>` — if `find_biblical_character_names` hit the allowlist, teach those names from notes+NKJV; else do not invent biographies
9. `<scripture_constraints>` — quote NKJV from notes only; never recommend Trevor Project / LGBTQ+ Hotline / Planned Parenthood
10. `<safety_protocol>` — crisis → in-person pastoral care + Nordin contacts; do not volunteer phone on a hello
11. `REFERENCE NOTES:\n` + formatted chunks

`uniqueness_instruction` and `classify_followup_intent` **are not added to this prompt on `development`.** They exist in `chat_retrieval.py` for tests and older experiments. Follow-up uniqueness is currently left to the user’s question plus retrieved notes (see the comment in `build_chat_system_prompt`).

Human message:

- Teaching: the English question
- Greeting: `CONVERSATIONAL_STEER` + question

Then LangChain messages:

```
[SystemMessage(system_filled), ...history Human/AI pairs..., HumanMessage(question)]
```

### 6.17 Token-budget trim — L12 — `fit_chat_budget`

While `prompt_tokens + completion + safety > window`:

1. Shrink `max_tokens` toward a floor of 512 (later 128 if still over)
2. Strip optional XML blocks in order: `<scope_policy>`, `<biblical_characters>`, `<safety_protocol>`
3. Clip REFERENCE NOTES from the end on paragraph/word boundaries (never replace with the old refusal string)
4. Clip instruction prefix, always keeping the `REFERENCE NOTES:\n` marker
5. Drop oldest history pairs, but keep at least one prior exchange
6. Last-resort: shrink notes to 240 chars, prefix to 600

`CHAT_TOKEN_SAFETY` default 96. Window is `min(CHAT_CONTEXT_WINDOW, VLLM_MAX_MODEL_LEN)`.

If notes get clipped, later claims in the PDF simply never reach the model. That looks like “the RAG was ignored.”

Returned `completion_tokens` is what `llm.bind(max_tokens=…)` uses. `CHAT_MAX_TOKENS=1024` is an upper bound, not a promise of 1024 output tokens.

### 6.18 First generate — L13 — `views._generate_tokens` + `chat_sse.py`

Streaming path (Flutter):

1. `iter_chat_tokens`: `bound_llm.stream(messages)` → take `.content` → split into ≤28-char pieces so the UI paints tokens, not one dump
2. Each piece becomes SSE `{"type":"delta","text":...}`
3. Cloudflare/browsers buffer small SSE. `sse_keepalive` sends a 4KB comment ping. `iter_with_sse_heartbeats` emits those every 2s while Django is blocked on embeddings or GPU cold start

Non-stream path: `bound.invoke(messages)` once (admin/tests). Same later loops.

Sampling on this call is the Qwen set in §4.2. `max_tokens` is the budget from L12.

### 6.19 Empty-stream retry — L14

Serverless workers often return LangChain `ValueError: No generation chunks were returned` while booting.

`_generate_tokens`:

1. First attempt, `iter_tokens_with_retries(..., attempts=1)` (no inner retry; Django already uses `VLLM_MAX_RETRIES` 1 on remote)
2. On failure before any token: log, `warmup_vllm_worker(force=True)`, rebuild client with **90s** timeout (`EMPTY_STREAM_RETRY_TIMEOUT_S`)
3. If still empty: trim system notes to ~3600 chars, halve `max_tokens` (min 256), try again
4. If still empty: `ChatGenerationError` with the user-visible GPU message

`is_retryable_stream_error` also retries timeouts, 502/503/504, connection resets. If tokens already started painting, it does **not** retry (that would duplicate the draft).

Inner LangChain HTTP retries are kept low (`1` remote, `2` local) because each retry enqueues another serverless job.

### 6.20 Expansion / continuation — L15

After the first draft:

`answer_needs_expansion` is true only when:

- The query is a teaching question (not a greeting)
- The text is not degenerate (CJK leak, legalese loops, 120-word low-variety clauses)
- **Either** the last sentence was cut mid-clause (`answer_looks_incomplete`) **or** the whole answer is under `MIN_TEACHING_CHARS` (1500) and has no “in conclusion” close ≥1000 chars

Then **at most `MAX_EXPANSION_PASSES = 1`** extra generate:

- Messages = original prompt + `AIMessage(first_answer)` + `HumanMessage(CONTINUE_STEER or FINISH_STEER)`
- `FINISH_STEER` if cut off: continue from the exact words; keep markdown; do not restart
- `CONTINUE_STEER` if merely short: continue without repeating sentences already on screen
- Token budget `continuation_token_budget` ≈ remaining chars to ~2000 / 3, capped by leftover completion
- `_trim_continuation_messages` is a fallback with clipped notes if the full continue prompt overflows

`join_continuation` / `strip_restarted_continuation` drop a prefix that restates the first answer (difflib ratio ≥0.82). If the model starts with “Let’s continue…” and then reprints, **only a prefix that already appears in the first draft is stripped**. A paraphrase reprint can still show up on screen. That is the reprint bug you have seen.

Degenerate CJK/legalese is **not** expanded (expanding it made Chinese dumps worse).

### 6.21 Claim-repair continue — L16

`_claim_repair_plan`:

- `uncovered_claims(answer, teaching_claims)`
- If any missing and completion budget > 0: `claim_repair_steer(missing)` + up to 384 tokens

This is another continue-pass with a different human steer: “You missed these retrieved points. Teach them now. Do not invent a different outline.”

If the first draft already closed, this pass is the main source of:

- A second outline glued under the first
- Suddenly teaching Alcohol / gifts / a different sermon that was sitting in notes 6–10 as a required point the first pass ignored

`join_continuation` again tries to strip a restarted copy.

### 6.22 Save, translate, sources — L17

`_save_ai_response` writes the **English** answer to `ChatMessage`. Follow-up retrieval reads this row next turn.

`display_reply`:

- English UI → return English
- Other UI → LLM translate (`temperature=0.2`) preserving markdown; **keep NKJV and Don/Susan quotations in English**

Live SSE only streams English deltas when `chat_language == "en"`. Other languages wait and send one delta of the translated full answer (so users do not see English then Spanish).

`_response_sources`:

1. Labels the model actually named in the answer (`sources_cited_in_answer` matches `Note N`, title stems, timestamps)
2. Pad to 3–5 distinct sermons (`RETRIEVAL_SOURCE_MIN/MAX`) via `ensure_source_media_mix`
3. Prefer mixing a written note and a video when both exist
4. Collapse timestamped clips of the same sermon to one chip
5. For named-entity questions, do not pad unrelated leftover sermons

These chips are **UI citations**. They do not change the already-generated wording. They can still surprise the user if diversity pulled extra sermons into notes.

### 6.23 SSE / Flutter paint — L18

Event types:

| SSE | Meaning |
| --- | --- |
| `: keepalive` + 4KB pad | Flush proxies during GPU wait |
| `status/started` | Prepare_chat has begun |
| `delta` | Append text to the live bubble |
| `done` | Final `answer`, `sources`, `message_id` |
| `error` | Show server error if nothing painted |

Flutter `completeChatStreamAnswer` overwrites the bubble with `done.answer` (so a translated full text replaces token scraps). `_boldBibleReferences` is **display-only** bolding of verse refs; it is not sent back to the model.

Stopping mid-stream finalizes the bubble; late tokens must not open a second one (`applyChatStreamDelta`).

---

## 7. The exact message the GPU sees

Conceptual OpenAI payload (vLLM then wraps it in the Qwen Instruct template):

```
model: christianai
temperature: 0.7
top_p: 0.8
presence_penalty: 0
frequency_penalty: 0
max_tokens: ≤ 1024 (often less after fit_chat_budget)
extra_body:
  repetition_penalty: 1.05
  top_k: 20
messages:
  - role: system
    content: |
      <priority>…</priority>
      <identity>…Don Nordin…Susan Nordin…713-800-5529…</identity>
      <scope_policy>…</scope_policy>
      <source_material>…REFERENCE NOTES first…required teaching points…</source_material>
      [optional <library_pull>]
      [optional <required_teaching_points> 1. … 2. …]
      <language>Write your entire reply in English…</language>
      <biblical_characters>…</biblical_characters>
      <scripture_constraints>NKJV from notes…</scripture_constraints>
      <safety_protocol>…</safety_protocol>
      REFERENCE NOTES:
      [Note 1 | Title]
      chunk body

      [Note 2 | Title [mm:ss–mm:ss]]
      chunk body
  - role: user      # prior turn
  - role: assistant # prior turn
  - …
  - role: user
    content: <English question or CONVERSATIONAL_STEER + hello>
```

Continue pass adds:

```
  - role: assistant  # first draft already streamed
  - role: user       # CONTINUE_STEER / FINISH_STEER / claim_repair_steer
```

That second user message is **not** the member talking. It is this repo steering the model.

---

## 8. File-by-file catalog (everything that influences a reply)

### 8.1 Always on the live generate path

| File | What it does to the answer |
| --- | --- |
| `frontend/lib/main.dart` | Sends query, session, language, regenerate; warms GPU; paints stream; display-only Bible bolding |
| `frontend/lib/services/api_client.dart` | HTTP shape of `/api/chat/` and `/api/chat/warmup/` |
| `frontend/lib/services/api_service.dart` | Thin wrapper used by the widget |
| `frontend/lib/chat_stream.dart` | SSE parse + bubble state |
| `frontend/lib/chat_input_limits.dart` | 1000-character cap |
| `frontend/lib/l10n/app_locale.dart` | Language code on the request |
| `backend/app/pastor_ai/urls.py` | Routes `/api/chat/` |
| `backend/app/api/permissions.py` | Premium/staff gate (no generate if unpaid) |
| `backend/app/pastor_ai/workspace_env.py` | Which vLLM URL/key the process actually uses |
| `backend/app/core/views.py` | **Orchestrator.** All online loops L1–L17 live here (`ChatAPIView.post`, `prepare_chat`, `_generate_tokens`, stream/non-stream) |
| `backend/app/core/chat_llm.py` | Client, sampling, token budget, empty-notes sentinel |
| `backend/app/core/chat_sse.py` | Token split, heartbeats, empty-stream retry classification |
| `backend/app/core/chat_language.py` | Language codes + English-only system block |
| `backend/app/core/chat_translate.py` | Inbound query translation, outbound reply translation |
| `backend/app/core/scope_gate.py` | YES/NO gate + decline writer |
| `backend/app/core/chat_system_prompt.py` | Identity/scope/source/safety prompt; greeting regex; continue/finish steers; incomplete/degenerate detectors; join_continuation |
| `backend/app/core/data/bible_names.txt` | Allowlist for biblical-name prompt annotation and retrieval entity tokens |
| `backend/app/core/chat_retrieval.py` | Query expand, search, filters, diversity, note formatting, library-pull, quote/verse extraction, source chips |
| `backend/app/core/teaching_claims.py` | Required points + coverage repair steer |
| `backend/app/core/grounding.py` | NKJV payload lookup used in chat (`lookup_nkjv_verses`, `verse_refs_for_lookup`) |
| `backend/app/core/bible_refs.py` | Book aliases and verse parsing used by lookup |
| `backend/app/core/quote_chunking.py` | `extract_quote_spans` / timestamp strip used at ingest **and** at claim extraction |
| `backend/app/core/embeddings_utils.py` | BGE encoder for search (same as ingest) |
| `backend/app/core/qdrant_utils.py` | Collection name/url; ensures indexes for verse lookup |
| `backend/app/core/models.py` | `ChatMessage` memory; `IngestedDocument` titles |
| `backend/app/core/vllm_warmup.py` | GPU boot ping |
| `start.sh` / `vllm_runtime.sh` / `serverless/vllm.env.example` | What weights, LoRA, max length, and env knobs the worker has |
| `config.env.example` | Documented defaults operators copy |

### 8.2 Offline, but they wrote the vectors the model reads

| File | What it does to later answers |
| --- | --- |
| `ingestion_service.py` | PDF/DOCX/markdown ingest loop, upsert payload shape |
| `document_cleanup.py` | Removes page chrome that would otherwise retrieve |
| `document_titles.py` | Source labels the model names |
| `bible_chunking.py` | Verse windows + `bible_verse` metadata |
| `video_ingestion.py` | Whisper → chunks with timestamps |
| `whisper_transcribe.py` / `whisper_remote.py` | Creates the transcript text |
| `transcript_normalize.py` | Drops fluff; formats `[mm:ss–mm:ss] line` |
| `video_topic_metadata.py` | Searchable header + overview chunk; optional LLM metadata |
| `website_crawl/pipeline.py` | Crawl then ingest |
| `website_crawl/crawler.py` | Fetch/allowlist |
| `website_crawl/extract.py` | HTML to markdown body |
| `website_crawl/config.py` | Which ministry domains exist in RAG |
| `docx_to_pdf.py` | DOCX becomes a stored PDF + extractable text |
| `ingestion_tasks.py` | Background job runner for admin uploads |
| `management/commands/reingest_grounded_rag.py` | Rebuilds vectors with current chunkers |

### 8.3 Present in repo, **not** on the live generate path

| File / symbol | Why it does not change today’s wording |
| --- | --- |
| `uniqueness_instruction` | Built in `chat_retrieval.py`, covered by tests, **not concatenated** in `prepare_chat` |
| `classify_followup_intent` | Same: intent classifier unused by `views.py` |
| `verify_answer_grounding`, `grounded_fallback_answer`, `GROUNDING_REPAIR_STEER` | Tests only; no post-answer rewrite |
| `ResponseReport` / thumbs UI | Staff inbox; no DPO/KTO training hook |
| `UserChatHistory` / `/api/chat/history/` | Sidebar sync only |
| `ingest_qdrant.py` | Legacy CLI |
| Prayer / events / billing / media list | Access and ministry tools, not prompt text |
| Flutter `_boldBibleReferences` | Cosmetic |

If you are debugging a bad *theological* answer, ignore the unused uniqueness/grounding helpers until they are wired back into `views.py`.

---

## 9. Environment knobs that change answers without editing Python

| Variable | Effect |
| --- | --- |
| `VLLM_MODEL` / `CHRISTIANAI_SERVED_NAME` | Must be `christianai` to hit the LoRA module |
| `CHRISTIANAI_BASE_VLLM` | Base weights |
| `VLLM_MAX_MODEL_LEN` / `CHAT_CONTEXT_WINDOW` | How much notes+history fit |
| `CHAT_MAX_TOKENS` | Output cap (1024 ≈ short-to-medium teaching, not a book) |
| `CHAT_TIMEOUT_S` | Local default 360; serverless often 600 |
| `CHAT_SCOPE_GATE` | `false` skips the YES/NO call |
| `RETRIEVAL_K` | Chunks offered to the prompt (24) |
| `RETRIEVAL_THRESHOLD` | 0.72 vs 0.8 is a big quality/coverage trade |
| `RETRIEVAL_CANDIDATE_MULTIPLIER` | 8 → 192 raw hits per query |
| `RETRIEVAL_MAX_PER_SOURCE` | 2 vs 4: how hard one sermon can dominate |
| `RETRIEVAL_BIBLE_RATIO` / `RETRIEVAL_VIDEO_RATIO` | Mix that causes mash-ups when raised |
| `RETRIEVAL_SOURCE_MIN/MAX` | How many chips the UI shows (3–5) |
| `CHAT_MAX_HISTORY_TURNS/CHARS` | How much prior outline the model can copy |
| `CHAT_MAX_CONTEXT_CHARS` | RAG character cap |
| `INGEST_CHUNK_SIZE/OVERLAP` | How fine the stored quotes are |
| `BIBLE_VERSES_PER_CHUNK` | NKJV packing |
| `BIBLE_SOURCE_MARKERS` | Which files use verse splitting |
| `EMBEDDING_MODEL_NAME` | Must match ingest |
| `VIDEO_TOPIC_METADATA_LLM` | Whether video headers are LLM-written |
| `WHISPER_MODEL` | Transcript quality |
| `PUBLIC_API_KEY` | If set, Flutter must send it or chat 401s |

Sampling constants in `chat_llm.py` are **not** env-driven. Changing temperature requires a code change.

---

## 10. Worked example: “expand the first point on marriage”

This is the loop trail for a follow-up, which is where RAG most often *looks* ignored.

1. Flutter sends `query="expand the first point"`, `session_id=<uuid>`, `language=en`, `stream=true`.
2. Django hashes session → loads last turns. Previous user line was “teach on marriage.”
3. Scope gate: `marriage` regex → skip LLM gate.
4. Not a greeting → expand queries. `prior_focus` ≈ `marriage`. Leading searches: `marriage`, `Pastor Don Nordin marriage`, `marriage <headings from last AI>`, `marriage expand first point` (after stopword strip, maybe just `marriage first point`).
5. Each query embeds with BGE; Qdrant returns ~192 cosine hits × queries; merge by fingerprint.
6. Topic filter keeps chunks mentioning marriage (and related metadata keywords).
7. Threshold 0.8 may drop weaker but relevant clips.
8. Diversity still injects Bible + maybe a second sermon/video (wine, gifts, intimacy) to fill 24 slots / 3–5 sources.
9. Notes formatted as `[Note 1 | Defining Marriage]…`. Claims extracted: covenant-not-contract, etc.
10. System prompt includes those claims + last AI’s full outline in history.
11. Budget may clip older notes or even the end of REFERENCE NOTES.
12. First generate often **reprints** the previous outline because it is sitting in history and the user said “expand.”
13. If under 1500 characters, continuation asks for more.
14. If claim coverage missed “covenant rather than contract”, claim-repair appends another section. If unused notes included alcohol, that section can appear here.
15. English saved; sources padded to 3–5 titles; Flutter replaces the bubble.

When people say “it stopped pulling from RAG,” the usual truth is: **RAG was mixed or clipped, history was strong, and a later continue-pass followed leftover claims.** The vectors were not empty.

---

## 11. Every generate-style LLM call in the product

A single user message can cause **multiple** `christianai` completions:

| # | Call | File | When |
| --- | --- | --- | --- |
| 0 | Video metadata JSON | `video_topic_metadata.extract_llm_metadata` | At video ingest, not at chat |
| 1 | Translate question → English | `chat_translate.translate_to_english` | Non-English UI |
| 2 | Scope YES/NO | `scope_gate.query_in_scope` | Query not on the regex allowlist |
| 3 | Out-of-scope paragraph | `scope_gate.generate_out_of_scope_reply` | Gate returned NO |
| 4 | Main teaching stream | `views._generate_tokens` | In-scope teaching/greeting |
| 5 | Retry of (4) with 90s timeout | same | Empty/cold stream |
| 6 | Retry of (4) with trimmed notes | same | Still empty |
| 7 | Continuation | `_iter_continuation_tokens` | Short or cut off |
| 8 | Claim repair | same, different steer | Missing required points |
| 9 | Translate answer → UI language | `display_reply` | Non-English UI |
| 10 | Batch translate old bubbles | `TranslateAPIView` | User changed language in the app |

Greetings skip 4’s RAG but still run (4). Out-of-scope skips 4–8.

---

## 12. How to chase a specific bad answer

Use this checklist against a saved `ChatMessage` id:

1. **Session history** — What were the previous `user_query` / `ai_response` rows? The model sees them verbatim.
2. **English query** — If the UI was not English, what did translation produce?
3. **Search queries** — Log line `Searching Qdrant with N queries`. If `marriage` is missing, retrieval will drift.
4. **Selected chunks** — Log `Selected retrieval chunks: total=… notes=… video=… bible=…`. Mixed media is a mash-up warning.
5. **Notes vs claims** — Claims come from quote sentences, not from the whole PDF. A PDF can be retrieved and still yield generic claims if contrast sentences never made `quote_text`.
6. **Budget** — Log `Chat token budget: prompt≈… completion=… history_msgs=…`. If notes were clipped, later sermons in the list never arrived.
7. **Which pass wrote the weird paragraph** — First stream, continuation, or claim repair? Repair is the usual “reprint then alcohol” machine.
8. **Sampling** — 0.7 temperature will paraphrase. The same notes will not yield the same wording twice.

---

## 13. Mental model in one paragraph

The GPU is **Qwen2.5-14B-Instruct-AWQ** plus a **rank-16 Christian LoRA** named `christianai`. It does not contain the sermon library. The library is **BGE-embedded chunks in Qdrant**, formatted as labeled `[Note N | Title]` blocks plus numbered **required teaching points**. Django decides *which* chunks, *what* instructions, *how many* tokens, and *whether* to run extra continue passes. vLLM only samples the next tokens under temperature 0.7 / top_p 0.8 / top_k 20 / repetition_penalty 1.05. Flutter only displays the stream. Votes do not train it. History is the Postgres `ChatMessage` table, not the sidebar backup.

That is the entire influence surface for how this AI responds.

---

## 14. Function index (role of each helper)

Use this as a jump list. “Live” means `ChatAPIView` calls it (directly or through a helper it calls). “Ingest” means it only runs when documents are added. “Unused live” means the function exists and is tested, but `views.py` does not call it.

### `views.py` (orchestrator)

| Function | Loop | Role |
| --- | --- | --- |
| `_strip_source_label` | L17 | Drops timestamps/extensions so PDF lookup by sermon name works |
| `_doc_source_name` | L10/L17 | Resolves a chunk to the admin title via `file_hash` |
| `_doc_source_label` | L10/L17 | Title plus `[timestamp]` for video notes |
| `_require_api_key` | L1 | Optional shared-secret gate |
| `_wants_chat_stream` | L1 | `stream=true` or `Accept: text/event-stream` |
| `_scoped_session_id` | L1 | Isolates memory per account + Flutter chat UUID |
| `_save_ai_response` | L17 | Writes English `ChatMessage` (or overwrites on regenerate) |
| `_chat_payload` | L17 | `{answer, sources, message_id}` |
| `_immediate_sse` | L3 | Streams a finished decline with no token loop |
| `_continuation_messages` | L15/L16 | Appends first draft + continue/repair human steer |
| `_join_continuation` | L15/L16 | Concatenates extra text after stripping a reprint |
| `_claim_repair_plan` | L16 | Missing claims → repair steer + token budget |
| `_trim_continuation_messages` | L15/L16 | Keeps system + last AI + last human so a continue still fits |
| `_iter_continuation_tokens` | L15/L16 | Streams the continue/repair generate; falls back to trimmed prompt |
| `prepare_chat` (inner) | L2–L12 | Scope, history, RAG, prompt, budget; returns `final` or `generate` |
| `_unique_sources` / `_response_sources` | L17 | 3–5 source chips |
| `_kick_worker` / `_short_timeout_bound` | L14 | GPU ping + 90s client |
| `_generate_tokens` | L13–L14 | Main stream + retries |
| `produce_events` / `token_events` | L13–L18 | SSE wrapper with heartbeats and error events |

### `chat_retrieval.py`

| Function | Live? | Role |
| --- | --- | --- |
| `expand_search_queries` | Yes | Builds the list of strings that get embedded |
| `keyword_search_query` | Yes | Drops “write a sermon about” filler before embedding |
| `topic_anchor_query` | Yes | `{last prior user} {current}` for topic filters |
| `looks_like_followup` | Indirect | Used by intent classifier; **intent classifier not used in views** |
| `looks_like_library_pull` | Yes | Triggers one-sermon lock + `LIBRARY_PULL_STEER` |
| `restrict_docs_to_primary_source` | Yes | One sermon + ≤2 Bible chunks |
| `search_queries_on_store` | Yes | The Qdrant cosine loop |
| `merge_scored_hits` | Yes | Best score per chunk fingerprint |
| `filter_hits_by_topic` | Yes | Lexical/name filter after ANN |
| `apply_retrieval_threshold` | Yes | Drops weak cosine hits |
| `select_diverse_docs` | Yes | MMR mix notes/video/Bible |
| `format_reference_notes` | Yes | `[Note N \| Title]\\ntext` blocks |
| `extract_used_quotes` / `extract_used_verse_refs` | Yes | Novelty + source chips |
| `extract_used_headings` | Yes | Prior AI headings appended to follow-up search |
| `sources_cited_in_answer` | Yes | Prefer chips the model named |
| `ensure_source_media_mix` | Yes | Pad 3–5 mixed sources |
| `is_bible_source` / `is_video_chunk` | Yes | Slot classification |
| `query_focus_tokens` / `query_entity_tokens` | Yes | What “on topic” means |
| `story_passage_for_query` | Yes | Extra “Genesis 4 Cain Abel” search string |
| `uniqueness_instruction` | **Unused live** | Would ban reused headings/quotes |
| `classify_followup_intent` | **Unused live** | Would distinguish clarify vs new topic vs apply |

### `chat_system_prompt.py`

| Function / constant | Live? | Role |
| --- | --- | --- |
| `build_chat_system_prompt` | Yes | Full identity/scope/source/safety text |
| `find_biblical_character_names` | Yes | Annotates `<biblical_characters>` |
| `biblical_characters_instruction` | Yes | The XML block itself |
| `looks_like_brief_social` | Yes | Skip RAG; conversational steer |
| `CONVERSATIONAL_STEER` | Yes | Prefix on hello |
| `LIBRARY_PULL_STEER` | Yes | One-sermon instruction |
| `CONTINUE_STEER` / `FINISH_STEER` | Yes | L15 human messages |
| `answer_needs_expansion` | Yes | Whether L15 runs |
| `answer_looks_incomplete` | Yes | Cut-off detector |
| `text_looks_degenerate` | Yes | Blocks expansion on CJK/legalese |
| `continuation_token_budget` | Yes | Caps L15 tokens |
| `join_continuation` / `strip_restarted_continuation` | Yes | Anti-reprint glue |
| `query_expects_long_answer` | Yes | Greetings stay short |
| `MAX_EXPANSION_PASSES = 1` | Yes | Only one L15 |

### `teaching_claims.py`

| Function | Live? | Role |
| --- | --- | --- |
| `extract_teaching_claims` | Yes | Up to 6 theses from retrieved notes |
| `format_teaching_claims_block` | Yes | Injects `<required_teaching_points>` |
| `claim_content_tokens` | Yes | Distinctive words after stopword strip (`faith` is a stopword) |
| `claim_is_covered` / `uncovered_claims` | Yes | Triggers L16 |
| `claim_repair_steer` | Yes | L16 human message |
| `claim_repair_token_budget` | Yes | ≤384 tokens |

### `chat_llm.py` / `chat_sse.py` / `scope_gate.py` / `chat_translate.py`

Covered in §§4, 6.3, 6.4, 6.18–6.19. Every public function in those files is on a live path except `notes_are_usable` (internal to budget) and test-only `reset_warmup_state_for_tests`.

---

## 15. The actual RAG block and the extra steers (verbatim)

These strings are what the model is reading, not comments in Discord.

**Note format** (`format_reference_notes`):

```
[Note 1 | Faith Lift]
# Faith Lift

You have been given THE measure of faith...

[Note 2 | Defining Marriage [12:04–12:31]]
# Defining Marriage
Topics: marriage, covenant
...
[12:04–12:31] Marriage is a covenant rather than a contract...
```

**Empty notes sentinel** (`EMPTY_REFERENCE_NOTES`):

> No sermon excerpts were attached for this turn. Do not invent Pastor Don or Susan quotations. Say you do not have retrieved notes for this question.

**Greeting prefix** (`CONVERSATIONAL_STEER`):

> This is a casual greeting or social check-in—not a teaching request. Reply in one short warm conversational paragraph (about 2–4 sentences). Do not quote Pastor Don or Susan…

**Cut-off continue** (`FINISH_STEER`):

> Your previous reply was cut off mid-sentence. Continue from the exact words where you stopped. Finish that sentence, then keep the same Markdown teaching already on screen… Do not restart, do not summarize, do not apologize…

**Short-answer continue** (`CONTINUE_STEER`):

> Your previous reply was too short. Continue the same teaching without restarting or apologizing. Do not repeat any sentence already written—the previous text is already on screen.

**Claim repair** (`claim_repair_steer`):

> Continue the same teaching without restarting or replacing the draft on screen. … You missed these retrieved Pastor Don/Susan teaching points. Teach them now in your own words. … 1. … 2. …

**Library pull** (`LIBRARY_PULL_STEER`):

> The user asked to pull up one sermon from the library. Stay inside the single retrieved sermon in REFERENCE NOTES. Do not mash other sermons into a new excerpt. Keep that sermon's actual thesis when you paraphrase.

**English language lock** (always on the generate path, even for English UI):

> Write your entire reply in English. Do not switch into Chinese or any other language mid-response. Do not insert Chinese, Japanese, or Korean characters.

That last block exists because Qwen2.5-14B is bilingual. Frequency penalties used to make Chinese the cheap next token; the current sampling + this instruction are the live defense.

---

## 16. What this document is *not*

It describes **`development` as of the commit this file landed on**. Open PRs may change loops without this file being updated yet. Known nearby experiments (not this live path unless merged):

- Session-wide retrieval from *all* prior user asks (not only the last line)
- Removing the continuation / claim-repair pass so there is a single generate
- Quote-ID slots (added, then removed)

When you debug production (`master`) vs development, confirm which of those loops are actually deployed. Sampling, RAG format, and the Qwen+LoRA pair are the stable core.

