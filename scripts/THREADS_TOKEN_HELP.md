# Threads token — Postman OAuth (short)

We **cannot** mint a user `access_token` from APP_ID + APP_SECRET alone. Posting needs a user OAuth `code`.

## 1. Meta App Dashboard

Paste this **exact** URL in both places:

`https://oauth.pstmn.io/v1/callback`

- Threads / product → **Authorize callback URL** (or Redirect URI)
- **Facebook Login → Settings → Valid OAuth Redirect URIs**

Keep Client OAuth Login + Web OAuth Login ON.

## 2. Local `.env`

```
VERIDIQ_THREADS_REDIRECT_URI=https://oauth.pstmn.io/v1/callback
```

(Must match Meta exactly.)

## 3. Open authorize URL

```
https://threads.com/oauth/authorize?client_id=1026312886913915&redirect_uri=https%3A%2F%2Foauth.pstmn.io%2Fv1%2Fcallback&scope=threads_basic%2Cthreads_content_publish%2Cthreads_manage_replies&response_type=code
```

Or: `python scripts/threads_exchange_code.py --print-url`

Approve `threads_basic` + `threads_content_publish` (+ `threads_manage_replies` if you will reply/comment).

## 4. Copy `code`, exchange

After redirect, Postman/browser shows `?code=...`. Paste **only the code** (or the full redirect URL):

```
python scripts/threads_exchange_code.py <code> --write-env
```

That writes `VERIDIQ_THREADS_ACCESS_TOKEN` + `VERIDIQ_THREADS_USER_ID`.

## Fallback (often Facebook-only)

- https://developers.facebook.com/tools/accesstoken/
- https://developers.facebook.com/tools/explorer/

May lack Threads scopes. If you have a candidate token, verify:

```
GET https://graph.threads.net/v1.0/me?access_token=TOKEN&fields=id,username
```

Success → use that token + `id` as USER_ID. Failure → stick to Postman OAuth above.

## Live test after paste (restart backend first)

```powershell
# Comment/reply first (needs parent Threads media id as target_ref):
# Marketing Agency → Advanced → channel=threads → Draft comment → Approve
# Or curl:
# POST /api/v1/veridiq/marketing/comments  {"channel":"threads","text":"hi","target_ref":"<MEDIA_ID>"}
# POST /api/v1/veridiq/comms/approve  {"draft_id":"...","approved":true,"channel":"threads_comment"}

# Then a short standalone post:
# Approve a threads queue draft (channel=threads), or:
# POST /api/v1/veridiq/platforms/threads/publish_text  {"text":"Veridiq live smoke"}
```
