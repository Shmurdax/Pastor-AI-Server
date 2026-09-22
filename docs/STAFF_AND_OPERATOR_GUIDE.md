# Nordin's AI — Operator and Staff Guide

This is the high-level guide for people who run the server and for ministry staff who manage users, sermons, subscriptions, prayer requests, and events. It explains **what the system is**, **how the pieces fit together**, and **what you actually click on day to day**. It does not cover install scripts, GPU settings, or other engineering internals.

For a first-time install or a pod restart, see the root [README](../README.md) and [RUNPOD.md](../RUNPOD.md).

For an engineering walkthrough of every loop that shapes a chat reply (base model, LoRA, ingest, RAG formatting, prompts, retries, continuations), see [How Nordin's AI Builds a Reply](AI_RESPONSE_PIPELINE.md).

---

## What this is

**Nordin's AI** is Pastor Don Nordin's public chat assistant, plus a small set of ministry tools around it.

Visitors ask questions about Scripture, Pastor Don's teaching, church life, and related faith topics. The assistant answers in a pastoral voice using:

1. **Pastor Don's materials** (sermon notes, PDFs, DOCX files, and crawled ministry websites)
2. **Scripture** (NKJV and related Bible sources in the same library)
3. A **Christian language model** tuned for this ministry

Staff also use the same site to take prayer requests, publish church events, and (from the Django admin) manage accounts, Premium memberships, and the sermon library.

The public site is the Flutter web app. The control panel is Django admin at a **private URL** (not `/admin/` — that path is a dead end). The operator keeps the private link in `config.env` as `DJANGO_ADMIN_URL` and shares it only with chosen staff.

---

## How it works (big picture)

Think of the stack as four layers. You only need to know what each layer is *for*.

| Layer | What it is | Why it matters |
| --- | --- | --- |
| **The website** | Chat, login, subscriptions, sermon library, prayer, events, media | What members and guests see |
| **Django** | Accounts, admin, prayer, events, billing records, document catalog | Where staff manage the ministry side |
| **The knowledge library** | Ingested sermons/PDFs plus website pages, stored as searchable chunks | What the chat "knows" besides the model itself |
| **The model** | The AI that writes the reply | Uses retrieved notes + conversation history to answer |

When someone asks a question:

1. The site sends the question to Django.
2. Django looks up the most relevant pieces of ingested teaching and Scripture.
3. Those notes, plus recent chat history, go to the model.
4. The model writes a pastoral answer. Source titles can appear so the person can open the related PDF.

If a file is not ingested, the chat cannot cite it. If a file is ingested, it becomes part of the library until someone deletes it.

Chat stays on Christian, biblical, church, and ministry topics. Off-topic questions are politely redirected.

---

## Who can do what

There are four kinds of people. The same email account can be both a member and staff.

| Role | How they get it | What they can do |
| --- | --- | --- |
| **Visitor** | Opens the site, no sign-in | Marketing landing page only. Must create an account and subscribe before any product access |
| **Member (unpaid)** | Registers with email/password or Google | Completes checkout. Cannot use chat, media, prayer, events, or the sermon library until Premium is active |
| **Premium member** | Pays (or staff grants Premium) | Chat, sermon library, prayer, events, media, and the Premium perks listed on the plans page |
| **Staff** | A superuser checks **Staff status** on their User | Same product access as Premium (no payment required), plus prayer inbox, create/edit church events, and (if they have the private admin URL) the Django control panel |

**Staff status** is the switch that unlocks ministry tools in the app. **Superuser** is the extra switch for full Django admin (users, documents, subscriptions). Typical client staff who manage the library and memberships should be **staff + superuser**, or staff with the specific admin permissions you want them to have.

The install creates a default admin account (`admin` / `admin123` unless overridden). Change that password before handing the server to a client.

---

## The public site

Open the public URL (Cloudflare tunnel or custom domain). Visitors who are not signed in with an active Premium subscription (or staff) see the **marketing landing page**. They must create an account or sign in, then complete checkout before the app opens.

### Chat

- Chat is paid-only. Guests and unpaid accounts cannot send messages.
- Signed-in Premium chats are tied to the account and sync history.
- The sidebar has **Sermons** (the ingested PDF library) and **Chats** (saved conversations).
- Premium keeps a longer history list (dozens of conversations).
- Microphone input is available where the browser supports it.
- Clicking a sermon title opens the stored PDF.

The assistant identifies itself as an AI for Pastor Don Nordin (it does not use a personal name). Contact details it may share for the ministry are the Nordins' published phone and `info@thenordins.org`.

### Accounts

From the landing page, login screen, or profile chip (after sign-in), people can:

- Create an account (name, email, password)
- Sign in with email/password
- Sign in with Google (when Google Sign-In is configured on the server)
- Sign out

Email is the username. Each account automatically gets a **Profile**, which holds avatar and subscription status.

### Subscriptions

The landing page and checkout use the current Premium prices. There is no public Free plan.

**Nordin's AI → Subscribe** (or **View plans** from the profile) is for **paid members** to switch monthly/yearly or cancel.

| Plan | Price | What is advertised |
| --- | --- | --- |
| Premium monthly | $15 / month | Chat, longer history, Walk through the Word videos, the Nordins' study notes, daily Bible reading |
| Premium yearly | $150 / year | Same Premium perks |

Checkout requires a signed-in account and happens immediately after signup/sign-in if the account is not Premium. If Stripe keys are configured, payment goes through Stripe Embedded Checkout. If Stripe is not configured yet, the site uses a **temporary mock checkout** that grants Premium without charging. Treat mock checkout as a test/demo path, not live billing.

Paid members can switch between monthly and yearly from the same plans page. The current price stays in effect until the end of the paid period; the new price is billed at the next renewal. A monthly member who switches to yearly keeps paying $15 until that month ends, then is billed $150/year.

Staff can also grant or revoke Premium in Django admin without a payment (see [Managing subscriptions](#managing-subscriptions)).

**Note:** The Media page currently shows a placeholder catalog and does not yet unlock full videos from a live Premium flag. Chat-history limits *do* follow Premium status.

### Prayer requests

Anyone with Premium (or staff) can submit a prayer from the chat screen (the prayer button). They can include name, email, and phone, or submit anonymously. Visitors on the landing page cannot submit prayers. Staff follow up in the in-app **Prayer inbox** or in Django admin.

### Church events

**Events** in the top nav opens the calendar overlay.

- Premium members and staff see **published** events only (staff also see unpublished events they manage).
- Staff who are signed in can add, edit, unpublish, and delete events from that same panel.

### Media

**Nordin's AI → Media** is the Walk through the Word library. Treat it as a front-end shell until real videos are wired in. The media API requires Premium (or staff).

---

## Staff work in the app (no Django required)

Give the person a normal member account, then check **Staff status** in Django (see [Managing users](#managing-users)). They sign in on the public site.

### Prayer inbox

Staff see a prayer icon in the header and a **Prayer inbox** button in their profile sheet.

- Filter: All / Needs follow-up / Followed up
- Open a request to read the text, contact info, and whether it was anonymous
- Mark followed up, add pastor notes, set contacted time
- Compose email in Gmail, Outlook, or the device mail app

Anonymous submissions hide the person's name/email in the public-facing fields; a linked account (if they were signed in) can still be visible to staff.

### Church events

Staff get an **Add event** control on the Events panel. Each event has title, description, location, host, start (and optional end), and a published flag. Unpublish to hide it from the public without deleting it.

---

## Django admin — the control panel

Go to `https://<your-public-url>/<DJANGO_ADMIN_URL>/` (the private path from `config.env`, printed by `start.sh`) and sign in with a staff/superuser account. Do not use `/admin/` — that address is intentionally a 404.

The home page has **Core Admin Tools** cards for ingestion and PDF browsing, plus the usual Django app lists.

You will mostly live in two groups on the admin home page:

- **Pastoral** — **Users** (accounts and subscriptions), **Profiles**, prayer requests, response reports, events, and **Mailchimp audience**
- **Content tools** — document/video ingestion and website scraping

Paid signups show up immediately under **Pastoral → Users**. The list includes email, plan (monthly/yearly), subscription status, and a Premium column. Open the user to edit the membership fields on the same page (the Profile section under the login fields).

---

## Managing users

**Pastoral → Users**

Each row is one login. Useful fields:

| Field | Meaning |
| --- | --- |
| **Username** | The email they signed up with |
| **Email** | Same address, used for contact and Google accounts |
| **First / last name** | Display name in the app |
| **Plan** | Monthly or yearly after they subscribe |
| **Subscription** | Free, Active, Past due, or Canceled |
| **Premium** | Yes when subscription status is Active |
| **Active** | Uncheck to disable login without deleting the account |
| **Staff status** | Unlocks prayer inbox, event editing, and the private admin URL (if they have permissions) |
| **Superuser** | Full admin, including other users |
| **Password** | Set or reset from this page |

When someone creates an account on the public site and pays, that User row is created right away. After checkout (Stripe or the temporary mock checkout), **Subscription** becomes **Active** and **Premium** is yes. If you only look at the old Users page fields (name/staff/active) you will miss the membership — use the Plan / Subscription / Premium columns.

**Typical client-staff setup**

1. Ask them to register on the public site (or create the user here).
2. Open their User record.
3. Check **Staff status**.
4. Check **Superuser** if they should manage users, documents, and subscriptions.
5. Save.

Do not delete the last superuser. If someone cannot reach the private admin URL, they are usually missing Staff status, or they are signing in on the public app with a different email than the admin user.

Google users are created on first Google sign-in. They look like normal Users; username is the Google email.

---

## Mailchimp audience export

**Pastoral → Mailchimp audience**

This page pushes Nordin's AI login emails into the ministry's existing Mailchimp audience so staff can send event and announcement campaigns from Mailchimp (from `info@thenordins.org`). The app does not compose or send those campaigns.

1. Operator sets `MAILCHIMP_API_KEY` and `MAILCHIMP_AUDIENCE_ID` in `tokens.env`, then runs `bash apply-tokens.sh` (restart Django if it is already running).
2. Staff open **Mailchimp audience**, confirm it shows the connected audience name and how many local emails will export.
3. Click **Export members to Mailchimp**. New contacts are added as subscribed, existing contacts are updated (name fields), and each contact is tagged `nordin-ai`. People who already unsubscribed in Mailchimp are skipped.
4. In Mailchimp, send the campaign to the audience or to the `nordin-ai` segment.

The default install account `admin@localhost` is never exported. Inactive accounts are skipped. From **Pastoral → Users** you can also select specific rows and use the **Export selected users to Mailchimp** action.

---

## Managing subscriptions

**Pastoral → Users** (preferred) or **Pastoral → Profiles**

Every user has one Profile. This is the membership record, now also shown on the User page.

| Status | Meaning | Premium in the app? |
| --- | --- | --- |
| **Free** | Default for new accounts | No |
| **Active** | Paid or manually granted | Yes |
| **Past due** | Stripe reported a failed/overdue payment | No |
| **Canceled** | Subscription ended | No |

Also on the profile:

- **Billing period** — monthly or yearly
- **Pending billing period** — scheduled switch (for example monthly → yearly) that takes effect at the current period end
- **Stripe customer / subscription IDs** — filled by Stripe; leave them unless engineering asks
- **Premium** column — a yes/no view of whether status is Active

**Grant Premium by hand:** open the User, set **Subscription status** to `Active` in the Profile section, optionally set billing period, save. The member may need to refresh or sign in again to see longer chat history.

**Revoke Premium:** set status back to `Free` or `Canceled`.

Stripe, when live, updates these fields from checkout and webhooks. Manual edits are the right tool for comps, pastors, and support cases. If Stripe later sends a cancel event, it can overwrite a manual Active status — flag that to engineering if it happens.

### Chat token budgets (Premium)

Premium members share one **platform monthly pool of 34,000,000 tokens** (calendar month). There is no per-user monthly allotment. When the pool is empty, Premium chat waits until the next month. **Superusers are never limited and do not consume the pool.**

The Django admin home page has a **Premium chat tokens** section showing tokens used, tokens left, and the monthly budget. Staff can also open **Premium chat token pools** under Pastoral.

Admins may still restrict an individual user via **Chat restricted until** / days+hours helpers (moderation only).

Chat copy when blocked: *You have used up your allotted responses currently. Please wait …*

Env knobs: `PLATFORM_MONTHLY_TOKEN_BUDGET` (default 34000000), `TOKEN_LIMIT_ENFORCE`.

---

## Managing ingested documents

This is the sermon / teaching library the chat searches. There are three related screens; they are not duplicates.

| Screen | Use it to |
| --- | --- |
| **Core → Document Ingestion** | Upload new PDF or DOCX files |
| **Core → Ingested Documents Browser** | Browse and open the stored PDFs |
| **Core → Ingested documents** | See titles, chunk counts, search, rename display titles, delete from the library |

### Adding sermons or notes

1. Open **Document Ingestion**.
2. Drag in files, or use **Select files…** / **Select folder…**. Only `.pdf` and `.docx` are accepted.
3. Leave **Replace existing source** unchecked for a normal add. Check it only when you are *replacing* a file that already has the same name.
4. Click **Run Incremental Ingestion**.
5. Large folders upload in small batches. Wait until the page comes back; then watch **Recent Ingestion Jobs**.

Job statuses:

- **Running** — still working. Refresh the page.
- **Completed** — files processed. Skipped = already in the library. Failed files are listed and can be opened from the job.
- **Failed** — the job itself stopped. Read the error on the job page. Jobs stuck "running" for a long time are auto-marked failed.

What ingestion does, in plain language: it keeps a PDF copy for the sermon library, cleans up page headers/footers so the chat is not confused by them, splits the text into passages, and adds those passages to the searchable library. The original PDF on disk is not rewritten.

DOCX files are converted to PDF so the sermon library can still open a link.

Duplicates (same file content) are skipped unless you checked replace.

### Browsing PDFs

**Ingested Documents Browser** lists the PDF folder: search by filename, page through, click to open. On the production host these files live on the persistent volume so they survive restarts.

### Renaming what members see

**Ingested documents** (the catalog, not the browser) has a **Title** field. That title is what chat source links and the app library use. The stored filename can stay ugly; edit the title to match the sermon name you want in the app.

### Removing a document

In **Ingested documents**, select the row(s) and delete (the admin action removes both the catalog entry and the matching search chunks). If a warning says Qdrant cleanup failed, tell engineering — Django may have dropped the row but leftover search pieces can remain.

Do not only delete the PDF from disk and leave the catalog row; the chat could still try to cite it.

### Website crawl

**Core → Website Crawl → RAG** pulls public pages from thenordins.org and allowlisted sister ministry sites (church, conference, and related ministry domains). Cart, checkout, login, admin, and social links are skipped.

Use this when ministry websites have new teaching or resource copy you want the chat to know. Check **Replace existing website sources** if you want a fresh crawl to overwrite the last one. Progress shows up under **Ingestion jobs**, same as file uploads.

---

## Other admin lists you may use

### Chat messages

**Core → Chat messages** is a log of questions and answers. If the person was signed in, **Sender email** is filled. Use this for support ("what did the bot tell them?") not as a pastoral CRM. Guests show an empty sender.

### Prayer requests

Same data as the in-app inbox. Useful if someone prefers the spreadsheet-style admin, bulk search, or marking **Followed up** inline. Pastor notes and contacted time live here too.

### Church events

Same events as the public Events panel. **Is published** can be toggled in the list. Unpublished events stay in admin but are hidden from non-staff.

### Ingestion jobs / job logs / file failures

Audit trail for uploads and crawls. If a batch "did nothing," look here for skipped duplicates vs failed files.

---

## Common tasks

**A new staff member needs access**  
They register on the site → you set Staff (and Superuser if they need the private admin URL) on their User.

**A member paid but the app still says Free**  
Check **Profiles** for that user. If status is not Active, set it. Ask them to refresh. If Stripe is live and still wrong, check that webhooks are configured (engineering).

**A member should get Premium without paying**  
Set their Profile **Subscription status** to Active.

**New sermon PDFs should show up in chat**  
Upload via Document Ingestion, wait for the job to complete, then ask a test question that should hit that sermon. Optionally tidy the **Title** on Ingested documents.

**Chat is citing an old or wrong file**  
Find it in Ingested documents. Either delete it, or re-upload with **Replace existing source** checked if the filename matches.

**Someone wants an account disabled**  
Uncheck **Active** on the User. Do not delete if you still need their prayer or chat history.

**Pod / server was restarted**  
Someone with server access should run the start script (see [RUNPOD.md](../RUNPOD.md)). Staff do not need to re-ingest unless the persistent sermon storage or database dump was missing.

---

## What this guide does not cover

Leave these to the people who maintain the host:

- Installing or updating the pod, GPU / model, tunnels, tokens
- Stripe dashboard products, webhook endpoints, Google OAuth client IDs
- Rebuilding the Flutter web UI
- Database dumps, Qdrant storage, or embedding internals

If chat is down for everyone, ingestion jobs never leave "running," PDFs vanish after a restart, or Stripe payments do not flip Premium, escalate rather than re-clicking admin actions.

---

## Quick map of URLs

| Where | What |
| --- | --- |
| `/` | Public app (chat, login, plans, events, media) |
| `/<DJANGO_ADMIN_URL>/` | Staff control panel (private; not `/admin/`) |
| `/<DJANGO_ADMIN_URL>/core/ingestion/` | Upload sermons |
| `/<DJANGO_ADMIN_URL>/core/ingested-documents/` | Browse stored PDFs |
| `/<DJANGO_ADMIN_URL>/core/website-crawl/` | Crawl ministry websites into the library |
