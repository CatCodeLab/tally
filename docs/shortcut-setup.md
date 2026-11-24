# iPhone Shortcut setup

## 摘要（中文）

Tally 的语音记账由一个手动搭建的 iPhone 快捷指令完成：你说或输入「40」或「Costco 40」，快捷指令把它连同时间和位置存进手机本地的 `queue.txt`（在「我的 iPhone」，不是 iCloud 云盘）。只有连上家里的 Wi-Fi 时才会把队列发给 Mac（`POST http://<主机名>.local:8766/api/voice`，请求头 `Authorization: Bearer <令牌>`），发送成功后才清空队列，并读出 Mac 返回的 `say`。不在家时只会提示「已暂存，回家后同步」。

步骤：先在 Mac 上运行 `tally pair --ssid "家里Wi-Fi名"` 得到主机名、端口、令牌；再按下面 1–9 步在「快捷指令」App 里逐个添加操作；最后添加到主屏幕，并设置 Siri 短语「Tally 记一笔」。隐私：开启 FileVault，不要把 `~/Tally` 放进桌面/文稿（iCloud 同步文件夹），如果开了 iCloud 设备备份请开启「高级数据保护」。令牌等同于密码，不要截图外传。

The rest of this document is in English.

---

## What this builds

A Shortcut named "Tally" that you trigger by Siri, Home Screen icon or Action Button. It asks for an amount and shop (spoken or typed), stamps it with time and location, saves it to a queue file on the phone, and, only when the phone is on your home Wi-Fi, sends the whole queue to your Mac and clears it.

Nothing leaves your home network. The Mac never needs the internet for this.

## Prerequisites

1. Mac and iPhone on the same home Wi-Fi.
2. `tally serve` is running on the Mac (it also starts the voice endpoint on port 8766; do not pass `--no-voice`).
3. Run `tally pair --ssid "YourHomeWiFiName"` on the Mac. It prints:

   ```
   Host: <name>.local
   Port: 8766
   Token: <long random token>
   SSID: YourHomeWiFiName
   ```

   The same values are on the dashboard at http://127.0.0.1:8765/pairing. Treat the token like a password. `tally pair --regenerate` makes a new one (the old one stops working at once; update the Shortcut).
4. On the iPhone, open **Settings > Privacy & Security > Local Network** after the first run and allow Shortcuts. If requests silently fail, check this first.
5. Open the Files app once and confirm **On My iPhone > Shortcuts** exists. If the folder is missing, run any Shortcut that saves a file and choose On My iPhone as the location (step 5 below creates it).

## The API in one place

```
POST http://<LocalHostName>.local:8766/api/voice
Authorization: Bearer <token>
Content-Type: application/json

{"items": [
  {"id": "20261124101530123-48213",
   "text": "Costco 40",
   "captured_at": "2026-11-24T10:15:30-05:00",
   "lat": 43.65, "lon": -79.38}
]}
```

- The `Authorization` value is exactly `Bearer ` followed by the token: capital B, one space, no quotes. The scheme is case-sensitive.
- `items`: 1 to 200 entries.
- `id`: 1 to 64 characters, unique per capture. It makes retries safe: re-sending an id returns `duplicate` and creates nothing.
- `text`: 1 to 500 characters.
- `captured_at`: ISO 8601 **with a timezone offset** (`-05:00` or `Z`). A date without an offset is rejected.
- `lat` / `lon`: optional. lat -90 to 90, lon -180 to 180. Leave the keys out when you have no location. Do not send empty strings.
- Body limit 256 KB (413 beyond that). A long offline backlog must be sent in chunks (see step 7).
- Response: JSON `{"results": [{"id", "status", "say"}, ...], "say": "..."}` where `status` is `recorded`, `review` or `duplicate`, and `say` is the sentence to speak.
- `401` bad or missing token. `422` bad body. Any other path or method returns `404`.

Important: the Shortcuts "Get Contents of URL" action does **not** fail on a 401 or 422; it just hands back the error body. That is why step 8 checks for `say` instead of trusting that "no error means success".

## Build the Shortcut

Open Shortcuts, tap **+**, and name it **Tally**. Add these actions in order. Action names below are as they appear in the current Shortcuts app; Apple renames things between iOS versions, so use the search box if one is not where described.

### 1. Pairing values: Text

Add four **Text** actions, each followed by **Set Variable**, so they are easy to edit later:

| Variable | Text |
|---|---|
| `Host` | `<name>.local` (from `tally pair`) |
| `Port` | `8766` |
| `Token` | the token |
| `HomeSSID` | your home Wi-Fi name, exactly as shown in Settings (case-sensitive) |

### 2. Ask for Input

**Ask for Input**: Input Type **Text**, Prompt `Amount / shop? 金额 / 商店？`. Leave "Allow Multiple Lines" off. Tapping the microphone on the keyboard gives dictation, so the same action covers speaking and typing. Under Siri it is read aloud and the answer is dictated. Then **Set Variable** `Spoken` to *Provided Input*.

The server accepts things like `40`, `$40`, `Costco 40` and free phrases; a bare number becomes an "Unknown shop" entry for you to name on the dashboard.

### 3. Location (optional)

1. **Get Current Location**.
2. **Get Details of Locations**: Get **Latitude**, then **Set Variable** `Lat`. Add another **Get Details of Locations** (input: the location) for **Longitude** and **Set Variable** `Lon`.

Honest limit: Shortcuts has no try/catch. If Location Services is off for Shortcuts, or no fix is available, **Get Current Location** can abort the whole run. Set the Shortcuts location permission to "While Using" or "Always" and "Precise" on. If you would rather never risk it, delete step 3 and use the no-coordinates branch in step 4 only.

### 4. Build the entry (Dictionary)

First compute the id and time:

1. **Current Date**, then **Format Date**: Date Format **Custom**, format string `yyyyMMddHHmmssSSS`. **Set Variable** `Stamp`.
2. **Random Number** between `1` and `999999`. **Set Variable** `Rand`.
3. **Current Date**, then **Format Date**: Date Format **ISO 8601**. Set Variable `When`. Run it once with **Show Result**: it must look like `2026-11-24T10:15:30-05:00` (an offset or `Z` at the end). If it has no offset, use Custom format `yyyy-MM-dd'T'HH:mm:ssxxx` instead.
4. **Combine Text** is not needed: in the Dictionary, the id value is a **Text** field containing the `Stamp` variable, a hyphen, and the `Rand` variable.

Then, to avoid sending empty lat/lon (which would be a 422), use an **If**:

- **If** `Lat` **has any value**:
  - **Dictionary** with keys: `id` (Text: `Stamp-Rand`), `text` (Text: `Spoken`), `captured_at` (Text: `When`), `lat` (**Number**: `Lat`), `lon` (**Number**: `Lon`). **Set Variable** `Entry`.
- **Otherwise**:
  - **Dictionary** with the first three keys only. **Set Variable** `Entry`.
- **End If**

### 5. Append to the queue (On My iPhone, not iCloud)

Goal: one JSON object per line in `On My iPhone > Shortcuts > queue.txt`.

1. Make the entry a single line of text. Add a **Text** action containing just the `Entry` variable. Shortcuts renders a dictionary placed in Text as JSON, but it is usually pretty-printed over many lines. Add **Replace Text**: Find `\s*\n\s*`, Replace With a single space, with **Regular Expression** turned on. Run once with **Show Result** to confirm the output is one line of valid JSON. (JSON escapes newlines inside strings, so replacing real line breaks is safe.) **Set Variable** `Line`.
2. **Get File**: choose **Shortcuts** under **On My iPhone** (not iCloud Drive) and the file `queue.txt`; turn **Error If Not Found** off. **Set Variable** `OldQueue`.
3. **If** `OldQueue` **has any value**: **Text** = `OldQueue`, a new line, `Line`; **Otherwise**: **Text** = `Line`. Set Variable `NewQueue`.
4. **Save File**: input `NewQueue`; turn **Ask Where to Save** **off**; destination folder **Shortcuts** under **On My iPhone**; Subpath `queue.txt`; **Overwrite If File Exists** **on**.

The first time you run this, the destination picker lets you choose the location. Pick **On My iPhone**, then the **Shortcuts** folder. Do not pick iCloud Drive: the queue holds your spending, location and the time of each capture.

There is also an **Append to Text File** action that does steps 2 to 4 in one go. Use it if, when you tap its file chooser, you can select a file under **On My iPhone**. It is not certain it offers that location on every iOS version (it tends to default to iCloud Drive's Shortcuts folder), which is why the Get File + Save File recipe above is the safe default.

After this step the entry is on the phone, so nothing is lost if the next steps fail.

### 6. Home Wi-Fi check

1. **Get Network Details**: **Wi-Fi** > **Network Name**. Set Variable `Net`. (Needs Location permission; iOS hides the SSID without it. On cellular this gives nothing.)
2. **If** `Net` **is not** `HomeSSID`:
   - **Show Result** (or **Speak Text**): `Saved, will sync at home / 已暂存，回家后同步`
   - **Stop This Shortcut**.
3. **End If**

### 7. Read the queue and send it

1. **Get File** `queue.txt` from **On My iPhone > Shortcuts** (same as step 5.2), then **Get Text from Input**.
2. **Split Text** by **New Lines**. Set Variable `Lines`.
3. Chunking. The server accepts 200 items and 256 KB per request. Normally you have a handful, so ignore this. After a long time away from home: **Get Item from List**/**Get Items from List** set to the first 200 items of `Lines` (Items in Range 1 to 200; the exact wording varies by iOS). Use that as `Lines`, and in step 8 keep the rest instead of clearing everything. If you do not do this and the backlog exceeds 200, the server answers 422 and nothing syncs until you trim the file by hand.
4. **Repeat with Each** item in `Lines`:
   - **Get Dictionary from Input** (input: *Repeat Item*).
   - **Add to Variable** `Items`.
   - **End Repeat**
5. **Get Contents of URL**:
   - URL: `http://` `Host` `:` `Port` `/api/voice`
   - Method **POST**
   - Headers: `Authorization` = `Bearer ` followed by `Token` (one space after Bearer; do not wrap in quotes). `Content-Type` is set by the JSON body automatically.
   - Request Body **JSON**: add one field, key `items`, type **Array** (or List), value the `Items` variable.
6. **Set Variable** `Response`.

If the JSON body editor will not accept a variable as the whole array, use this fallback instead of 4 and the JSON body: **Combine Text** `Lines` with custom separator `,`; **Text** = `{"items":[` + that + `]}`; in Get Contents of URL set Request Body **File** with that text, and add the header `Content-Type: application/json` yourself.

### 8. Clear the queue only on success, then speak

Remember: a 401 or 422 does not raise an error, so test for a `say` in the reply rather than assuming.

1. **Get Dictionary Value**: key `say`, from `Response`. Set Variable `Say`.
2. **If** `Say` **has any value**:
   - **Text** (empty; leave the field blank), then **Save File** to **On My iPhone > Shortcuts**, Subpath `queue.txt`, **Overwrite If File Exists** on, Ask Where to Save off. (If you chunked in step 7.3, save the remaining lines instead of an empty text.)
   - **Speak Text** `Say`.
3. **Otherwise**:
   - **Speak Text**/**Show Result**: `Sync failed, items kept / 同步失败，已保留`. Do not touch the queue.
4. **End If**

If the phone cannot reach the Mac at all (Mac asleep, wrong host, Local Network blocked), **Get Contents of URL** raises an error and the Shortcut stops before this step, so the queue is also kept. Ids make re-sending safe: a retry after a half-finished sync returns `duplicate` for items the Mac already has and never double-counts.

Edge case: if the Mac recorded your items but the phone lost the response (Wi-Fi dropped), the queue stays and the next sync reports them as duplicates, then clears. That is expected.

### 9. Home Screen and Siri

1. Tap the Shortcut's name > **Add to Home Screen** (and/or assign it to the Action Button in Settings).
2. Siri phrase: rename the Shortcut to `Tally 记一笔`. Siri runs a Shortcut by its name, so saying "Tally 记一笔" works. Add an English alias by duplicating the Shortcut as "Tally" if you want both phrases.

## Privacy setup (spec section 5.7)

- Turn on **FileVault** (System Settings > Privacy & Security > FileVault). The database and receipts are only as private as the disk.
- Keep `~/Tally` out of **Desktop** and **Documents**. If iCloud Drive's "Desktop & Documents Folders" is on, anything there is uploaded. The default `~/Tally` in your home folder is not synced; if you set `TALLY_HOME`, keep it outside those folders too.
- If **iCloud device backup** is on, turn on **Advanced Data Protection** so backups (which include the phone's local files) are end-to-end encrypted.
- The queue file lives in **On My iPhone**, not iCloud Drive, so it is not synced between devices.
- The Shortcut only sends when the Wi-Fi name matches `HomeSSID`. The voice port (8766) is the only thing exposed to the LAN; the dashboard (8765) listens on 127.0.0.1 only.
- The queue is cleared after a successful sync.
- Anyone on your Wi-Fi who learns the token can post entries. Rotate it with `tally pair --regenerate` if it leaks.

## Test it

1. On home Wi-Fi, run the Shortcut and say "40". You should hear "Recorded: Unknown shop $40.00, ... please check", and an "Unknown shop" entry appears under Review on the dashboard.
2. Name the shop on the dashboard, then say "12" again at the same place; the shop is filled in automatically.
3. Turn Wi-Fi off. Run it: it says "Saved, will sync at home". Come home, run it again: both items sync and `queue.txt` is empty afterward (open it in Files to check).
4. Run it again right away: no duplicates appear.

## Troubleshooting

- Nothing arrives: open `http://<name>.local:8766/api/voice` in Safari; a `404` page means the server is reachable (GET is deliberately not allowed). A timeout means the Mac is asleep, `tally serve` is not running, or Local Network access is off.
- `.local` does not resolve: use the Mac's IP address in `Host` instead (set a DHCP reservation so it does not change).
- Always says "Sync failed": token mismatch (401) or a bad field (422). Show the `Response` with **Show Result**.
- `tally doctor` checks the Mac side.
