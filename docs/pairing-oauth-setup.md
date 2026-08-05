# Desktop OAuth client setup (one-time, user)

The desktop sync agent authenticates to *your own* Google Drive. You create one
Desktop OAuth client in a Google Cloud project you own.

1. Go to https://console.cloud.google.com/ → create (or pick) a project.
2. APIs & Services → Library → enable **Google Drive API**.
3. APIs & Services → OAuth consent screen:
   - User type: **External**.
   - Fill app name / support email / developer email.
   - Scopes: add **`https://www.googleapis.com/auth/drive`**.
   - **Publishing status: click "PUBLISH APP" → Production.** Do NOT leave it in
     "Testing" — testing-mode refresh tokens expire after 7 days and you would
     re-consent weekly (P13). Add yourself as the user if prompted.
4. APIs & Services → Credentials → Create Credentials → **OAuth client ID** →
   Application type: **Desktop app** → create.
5. Download the client JSON. Save it as:
   `omni_capture/client_secret.json`  (this path is gitignored — never commit it).
6. Use the **same Google account** on the phone. The phone uses a separate
   **Android** OAuth client (SHA-1 registered) requesting the same
   `auth/drive` scope — set that up when the phone-side pairing lands.

First run of the agent opens a browser for consent once; the token is cached at
`omni_capture/.drive_token.json` (also gitignored) and refreshed automatically.

## D0 live gate — run once `client_secret.json` is in place

From `omni_capture/`:

```bash
python -c "from drive_auth import get_drive_service; s=get_drive_service(); print([f['name'] for f in s.files().list(q=\"name='SecondThoughtVault' and mimeType='application/vnd.google-apps.folder' and trashed=false\", fields='files(id,name)').execute().get('files', [])])"
```

Expected: a browser opens for consent once, then it prints a Python list
(`[]` is fine — the hub folder doesn't exist until D1 creates it). A printed
list with no auth error is the D0 pass.
