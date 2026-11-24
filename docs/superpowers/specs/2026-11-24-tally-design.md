# Tally — Local Cash Receipt Tracker: Design

Date: 2026-11-24
Status: Approved 2026-11-24

## 1. Intent and why

The user currently keeps no budget and wants to **see, each month, where their cash goes**. Card spending is already visible in bank statements; this tool covers **cash only**.

The single most important property is **low effort**. Taking a photo at every purchase was explicitly rejected as too much hassle. The workflow is therefore: pocket the receipt → drop it in a box → batch-scan the box about once a week. Everything after that (reading, categorizing, totalling) is automatic, with human attention requested only when the program is unsure.

**Success:** opening a local web page and seeing, for any date range, how much cash went to each category and shop, plus how much withdrawn cash is unaccounted for, without the user having kept any manual records beyond receipts and ATM withdrawals.

## 2. Goals, non-goals, anti-goals

**Goals**
- Batch-ingest receipt images from a folder; extract shop, date, total; auto-categorize.
- Local web dashboard with charts; filter by date range, category, shop.
- Track cash withdrawals so the dashboard can show **Unaccounted = Withdrawn − Recorded**.
- Quick manual entry for cash spending that had no receipt.
- English and Chinese receipts; UI in English and Chinese (switchable).

**Non-goals (v1)**
- Card / bank statement import. Card spending is already tracked elsewhere.
- Screenshots of e-receipts or online orders.
- Multiple currencies. Everything is **USD**.
- Line-item (per-product) extraction. Only the receipt total.
- Mobile app, multi-user, sync, or accounts.
- Budgets, alerts, or forecasts.

**Anti-goals (would be failure even if it "works")**
- **Any data leaving the machine.** Receipt images, OCR text, and the database must never be sent to a cloud service. No cloud OCR, no cloud LLM, no CDN-loaded scripts on the dashboard, no telemetry.
- **Silently wrong amounts.** A plausible but invented total is worse than a flagged one.
- **High-maintenance correction.** If the user has to fix most receipts by hand, the tool has failed its purpose.

## 3. Constraints

- **Machine:** Apple M4, 24 GB RAM, macOS 15.7. Ollama already installed (has `llama3.2-vision:11b`, `llama3.2`, `llama3`, `deepseek-r1:8b`; no Qwen models yet). Python 3.12 and `uv` available.
- **Fully local:** see anti-goals.
- **Currency:** USD only. Chinese-language receipts are from US shops and are also in USD. (The `¥` in the mockups is a leftover placeholder; the real UI uses `$`.)
- **Receipt languages:** English and Chinese, possibly mixed in one folder.

## 4. Approaches considered

**Reading receipts (decided: A)**

| | Approach | Trade-off | Outcome |
|---|---|---|---|
| — | Claude vision API | Most accurate, but sends photos to the cloud | Ruled out by the local-only requirement |
| **A** | **macOS Vision OCR → local text LLM (Ollama) extracts fields** | Fast (seconds per receipt); OCR digits are reliable; the extracted total can be **verified against the OCR text**. Slightly more code (Python → macOS Vision bridge) | **Chosen** |
| B | Local vision LLM reads the image directly | Simplest pipeline, but slow (15–30 s each), can hallucinate digits with nothing to cross-check, and weaker on Chinese | Rejected |
| — | OCR + hand-written parsing rules | Free and simple, but brittle across receipt formats → frequent manual fixes | Rejected (conflicts with low effort) |

**Capturing receipts (decided: weekly batch scan)**
- Per-purchase photo: rejected by the user as too much hassle.
- Voice entry at each purchase: still a per-payment action, but much faster than a photo, and it covers cash spending with no receipt. **Added as a second input path** (§5.2a), alongside the batch scan.
- **Weekly batch scan with iPhone Continuity Camera** (Finder → right-click folder → "Import from iPhone → Scan Documents"): no action at payment time, and transfer is device-to-device rather than through iCloud. **Chosen.**

**Dashboard layout (decided: A, "this month overview")**, chosen over a 6-month-trend-first layout.

## 5. What was decided

### 5.1 Inputs
1. **Receipt images**: files dropped into an inbox folder (default `~/Tally/inbox/`, configurable). Formats: JPEG, PNG, HEIC, and PDF (Continuity Camera's "Scan Documents" can save PDFs, sometimes multi-page; one page = one receipt).
2. **Manual cash entries**: shop/description, amount, date (default today), optional category. Available from both the CLI and a form on the web page.
3. **Cash withdrawals**: amount and date. Available from both the CLI and the web page.
4. **Voice entries from iPhone**: see §5.2a.

### 5.2a Voice entry (iPhone → Mac, local network only)
- **What the user does:** at payment time, taps an iOS Shortcut on the home screen (or asks Siri) and says one sentence in English or Chinese, e.g. "McDonald's twelve fifty yesterday" or "菜市场 40". No further action.
- **Speech to text:** iOS built-in dictation, on-device. No third-party speech service.
- **Transport (decided: queue on phone, send on home network):**
  - The Shortcut stores each utterance in a queue on the iPhone, each with a unique id generated on the phone and the capture timestamp.
  - On every run, the Shortcut first tries to send all queued items to the Mac over the home Wi-Fi.
  - If the Mac is unreachable (away from home, or the Mac is asleep), the Shortcut replies "Saved, will sync at home" and keeps the queue.
  - Nothing goes through iCloud, a VPN, or any relay. Tailscale-style remote access was considered and rejected because it routes data over the internet.
- **On the Mac:**
  - A receive endpoint on the local network, protected by a shared secret token that is set up once during pairing.
  - The endpoint parses the sentence with the same local LLM into `{shop, amount, date, category}`. Relative dates ("yesterday", "昨天") resolve against the **capture timestamp**, not the sync time. If no date is given, the capture date is used.
  - Entries are stored with source = `voice` and the original sentence. Re-sent items with an already-seen id are ignored, so retries never double-count.
  - Entries with a missing or unparseable amount go to **needs review**.
- **Feedback:** if the send succeeds immediately, Siri reads back "Recorded: McDonald's $12.50, Food". Queued items get no readback, and the user can check or fix them on the web page later.
- **Typed input:** the same Shortcut accepts typed text instead of speech ("菜市场 40"), handled identically. Only **text** is ever sent; no audio is recorded or transmitted.
- **Location → shop (decided: learn locally):**
  - Each entry also carries the phone's GPS coordinates (from iOS, with no lookup service called) so the user can say **just the amount** ("40").
  - The Mac keeps a local **places** table that maps a coordinate cluster to a shop.
  - **No shop spoken, known place nearby (≈50 m):** the shop and its remembered category are filled automatically. If several known shops are nearby (e.g. a mall), the most frequent is chosen and the entry goes to **needs review**.
  - **No shop spoken, unknown place:** saved as "Unknown shop (near …)" in needs review. Once the user names it on the web page, that location is remembered.
  - **Shop spoken:** what the user said wins, and the location is learned or updated for that shop.
  - Apple Maps reverse geocoding was considered and rejected because it sends location to Apple, and it often returns a street or mall rather than the shop.
- **Dashboard:** voice entries appear alongside receipts, marked with a 🎤 icon and the original sentence instead of a photo.

### 5.2 Processing pipeline (per new image)
1. Skip if already processed, using the content hash of the file.
2. OCR with macOS Vision (languages: en-US, zh-Hans, zh-Hant). Store the raw OCR text.
3. Send the OCR text to a local Ollama text model with a JSON schema: `{shop, date, total, category, confidence}`. The model also normalizes the shop name (e.g. `MCDONALD'S #4521` → `McDonald's`).
4. **Verification**: the extracted total must appear in the OCR text as a number. If not, or if date/total is missing, or if confidence is low, the receipt is marked **needs review**.
5. **Category memory**: if this normalized shop has a user-confirmed category, use it and ignore the model's guess.
6. **Possible duplicate**: same shop, date and total as an existing receipt → flag as needs review instead of double-counting.
6a. **Payment method** *(Claude's call)*: the model also extracts `payment_method` ∈ {cash, card, unknown}, using cues such as "CASH TENDERED / CHANGE" or "VISA ****1234". **Card** receipts are kept in the archive but **excluded from all totals**, and are listed under a "Skipped: card" view where the user can override. **Unknown** is treated as cash, since many cash receipts don't say so.

**How flagged receipts count** *(Claude's call)*:
- Low-confidence or unverified reads **are counted** using the best-guess values, and the totals row shows "incl. $X unconfirmed" until they are reviewed. This keeps Unaccounted from being inflated in the meantime.
- Suspected duplicates are **not counted** until the user confirms they are separate purchases.
- Each receipt therefore has a status: `ok`, `needs_review`, `suspected_duplicate`, `card_skipped` or `deleted`.
7. Move or copy the original image into the managed archive (`~/Tally/receipts/YYYY/MM/`) so the inbox empties out.

Scanning is triggered by `tally scan` or a **"Scan new receipts"** button on the web page.

### 5.3 Categories
Fixed starter list, user-extendable: **Food** (eating out), **Groceries**, **Clothes**, **Transport**, **Household**, **Entertainment**, **Health**, **Other**. Each category has an English and a Chinese display name. When the user changes a receipt's category, that choice is remembered for the shop.

### 5.4 Web dashboard (local only)
Served on `127.0.0.1`, with no external network requests. All JS and CSS (including the charting library) are bundled locally.

- **Header:** date-range label; ‹ › shifts the range by its own length; **EN / 中文** switch, remembered between visits.
- **Date-range picker:** presets *This month* (the default on open), *Last month*, *Last 3 months*, *This year*, and *Custom* from/to.
- **Filters:** category and shop, on top of the date range.
- **Totals row:** *Cash withdrawn*, *Recorded*, *Unaccounted* (= withdrawn − recorded within the range).
- **Donut chart:** spending by category; clicking a slice filters to that category.
- **Bar chart:** weekly bars when the range is ≤ 2 months, monthly bars otherwise.
- **Top shops:** total and visit count; clicking one filters to that shop.
- **Receipt list / detail:** clicking a receipt shows the image next to the extracted fields; the user can edit shop, date, total and category, or delete the receipt.
- **Needs review badge** (⚠ N to review) opens a queue of flagged receipts to confirm or fix.
- **Add cash entry** and **Add withdrawal** forms.
- Shop names are shown as stored (normalized from the receipt), not translated.

Approved mockups: `.superpowers/brainstorm/*/content/monthly-overview-v3.html`.

### 5.5 CLI
`tally scan`, `tally add <amount> <shop> [--date] [--category]`, `tally withdraw <amount> [--date]`, `tally serve` (starts the dashboard and opens the browser).

### 5.6 Storage
A single local SQLite file (default `~/Tally/tally.db`) plus the image archive. Images are kept permanently so any entry can be re-checked.

## 5.7 Security requirements
Threat surface: the home LAN, other processes and websites on the Mac, and anyone who obtains the database or backups. Requirements, most important first:

1. **Send only on the home Wi-Fi.** Before sending, the Shortcut checks the current Wi-Fi network name (SSID) against the home SSID stored at pairing. On any other network it only queues. This prevents a spoofed `.local` host on public Wi-Fi from receiving queued entries or the token. LAN traffic is plain HTTP, so this check is the main protection.
2. **Don't keep a location trail.** After an entry is matched to a place, its raw coordinates are **discarded**, and the entry stores only a `place_id`. Raw coordinates live only in the places table, as one representative point per place. Setup docs tell the user to enable FileVault, and the data directory must not be inside an iCloud-synced folder (Desktop/Documents).
3. **Clear the phone queue after a successful sync.** Successfully sent items are removed from the iPhone queue immediately to limit exposure via iCloud device backup. Setup docs mention Advanced Data Protection.
4. **Protect the localhost dashboard from websites.**
   - Reject requests whose `Host` is not `127.0.0.1` or `localhost`, to block DNS rebinding.
   - Require a CSRF token on every state-changing request.
   - Send no permissive CORS headers.
5. **Treat OCR and voice text as untrusted.**
   - Escape all user- or model-derived text when rendering it.
   - The LLM has no tools. Its output must validate against the JSON schema, and anything that fails validation goes to needs review.
6. **The voice endpoint is write-only and token-protected.**
   - It accepts only "add entry" requests and exposes no read API.
   - The token is long and random, and it can be regenerated (re-pairing) from the CLI or the web page.
   - Requests without a valid token are rejected.
7. **Supply chain.** Dependencies are pinned via `uv.lock`, and the frontend libraries are vendored. Setup verifies that Ollama is listening on `127.0.0.1` only (its default) and warns if it isn't.

## 6. Builder's calls (decided by Claude, open to change)
- Card-receipt detection and exclusion, and how flagged receipts count toward totals (see §5.2).
- Network layout for voice:
  - The dashboard stays bound to `127.0.0.1`.
  - Only the token-protected voice endpoint listens on the LAN.
  - The Mac is reached by its `.local` (Bonjour) hostname.
- How the iOS Shortcut is delivered: a signed `.shortcut` file (via macOS `shortcuts sign`) plus a one-time pairing step that stores the Mac address and token. Step-by-step manual instructions are the fallback.
- Python 3.12 managed with `uv`; package/CLI name `tally`.
- Web stack: a small Python web server (e.g. FastAPI) with server-rendered pages or a light frontend. Chart.js or similar, **vendored locally**.
- macOS Vision access via a Python binding (e.g. `ocrmac`/PyObjC) or a tiny Swift helper, whichever proves more reliable.
- Default text model: `qwen2.5:7b` (strong at Chinese + English and JSON output). Needs a one-time `ollama pull`; configurable.
- Exact confidence threshold, duplicate rules, the prompt wording, and the schema details.
- Test fixtures: a small set of sample receipt images and their expected extractions.
