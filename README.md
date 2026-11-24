# tally

Local cash-spending tracker for macOS. Receipts (scanned with iPhone Continuity Camera) and voice notes (an iPhone Shortcut) become entries in a private dashboard. Everything runs on your Mac: OCR is Apple Vision, the language model is Ollama on localhost, and the data is a SQLite file in `~/Tally`.

## Install

Requires macOS, Python 3.12+, [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com).

```
uv sync
ollama pull qwen2.5:7b
uv run tally doctor
```

`tally doctor` checks the data folder, database, OCR and that Ollama and the model are reachable. Fix anything marked with a cross before continuing.

Data lives in `~/Tally` (override with `TALLY_HOME`): `tally.db`, `receipts/` (archived images) and `inbox/`. Keep it out of Desktop and Documents so iCloud does not upload it.

## Weekly flow

1. In Finder, right-click the folder `~/Tally/inbox`, choose **Import from iPhone > Scan Documents**, and scan your receipts with the iPhone.
2. Run `tally scan`, or click **Scan new receipts** on the dashboard.
3. Open the dashboard, review anything flagged (unreadable total, suspected duplicate, unknown shop) and fix it.

## Commands

| Command | What it does |
|---|---|
| `tally serve [--no-voice] [--no-open]` | Starts the dashboard at http://127.0.0.1:8765 (localhost only) and the phone voice endpoint on port 8766. `--no-voice` skips the endpoint; `--no-open` does not open the browser. |
| `tally scan` | Reads new images and PDFs from the inbox. |
| `tally add AMOUNT SHOP [--date YYYY-MM-DD] [--category SLUG]` | Adds an entry by hand. |
| `tally withdraw AMOUNT [--date YYYY-MM-DD]` | Records a cash withdrawal. |
| `tally pair [--regenerate] [--ssid NAME]` | Prints the host, port, token and home Wi-Fi name for the phone; `--regenerate` rotates the token. |
| `tally doctor` | Checks the local setup. |

Run them with `uv run tally ...`.

## Phone voice capture

An iPhone Shortcut records "Costco 40" by voice or typing, queues it on the phone, and syncs it to the Mac when you are on the home Wi-Fi.

1. `uv run tally pair --ssid "YourHomeWiFiName"`
2. `uv run tally serve`
3. Build the Shortcut by hand from [docs/shortcut-setup.md](docs/shortcut-setup.md) (it also has a short Chinese summary). The same guide is on the dashboard under **Phone pairing**.

The voice endpoint is `POST http://<name>.local:8766/api/voice` with header `Authorization: Bearer <token>`; it is the only thing reachable from your LAN, and every other path returns 404. The token is a secret: rotate it with `tally pair --regenerate`.

## Privacy

- Turn on FileVault.
- Keep `~/Tally` out of Desktop and Documents (iCloud).
- Turn on Advanced Data Protection if iCloud device backup is on.
- The phone's queue file is stored On My iPhone, not iCloud Drive, is sent only on the home Wi-Fi, and is cleared after a successful sync.

## Development

```
uv run pytest
```
