"""Sign-in to the declaut account, over Supabase Auth's REST API.

`sign_in` exchanges email + password for a session, `access_token` hands out
a valid token for the license API (renewing it first when needed), and
`sign_out` ends the session on this PC. Sign-up, email confirmation and
password reset happen only on the website (see config.WEBSITE_URL).

The refresh token lives in the OS credential store (Windows Credential
Manager, via `keyring`), never in the SQLite file; the access token is kept
in memory only. Plain urllib like anaf_client, so no Supabase SDK is bundled.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import keyring
from keyring.errors import KeyringError

from config import APP_VERSION, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL

_TIMEOUT = 15  # seconds
_USER_AGENT = f"declaut/{APP_VERSION}"
_KEYRING_SERVICE = "declaut"
# Renew the access token this long before it expires, so a request started
# just before the deadline does not reach the server with a dead token.
_EXPIRY_MARGIN_S = 60

_MSG_OFFLINE = ("Serverul de conturi nu poate fi contactat. Verificați "
                "conexiunea la internet și încercați din nou.")
_MSG_SIGNED_OUT = "Nu sunteți autentificat."
_MSG_EXPIRED = "Sesiunea a expirat. Autentificați-vă din nou."


class AuthError(Exception):
    """The account service refused the request, or there is no session.
    The message is in Romanian, ready to show as is."""


class AuthOffline(AuthError):
    """The account service could not be reached (no network, timeout, 5xx).
    The stored session is kept: it may still be valid once back online."""


# Current session. The access token is short-lived (1 hour by default) and is
# never written to disk; after a restart the stored refresh token renews it.
_access_token: str | None = None
_expires_at = 0.0  # time.monotonic() value; immune to the PC's clock changing

# Refresh tokens are single-use: each renewal returns a new one. The startup
# license check (background thread) and the UI can both ask for a token, so
# renewals are serialized to keep two of them from spending the same one.
_lock = threading.Lock()


def _keyring_account() -> str:
    """The stored session belongs to one Supabase project, so staging and
    production keep separate entries instead of overwriting each other."""
    return urllib.parse.urlsplit(SUPABASE_URL).netloc or "unconfigured"


def _load_refresh_token() -> str | None:
    try:
        return keyring.get_password(_KEYRING_SERVICE, _keyring_account())
    except KeyringError:
        return None


def _save_refresh_token(token: str) -> None:
    # A credential store that refuses the write (locked, missing) only costs
    # persistence: this run stays signed in, the next start asks again.
    try:
        keyring.set_password(_KEYRING_SERVICE, _keyring_account(), token)
    except KeyringError:
        pass


def _forget_refresh_token() -> None:
    try:
        keyring.delete_password(_KEYRING_SERVICE, _keyring_account())
    except KeyringError:  # includes "nothing stored"
        pass


def _error_message(status: int, body: bytes) -> str:
    """Romanian text for a 4xx answer. Supabase reports the reason as
    `error_code` (current API) or in `error_description` (older one)."""
    try:
        info = json.loads(body)
    except ValueError:
        info = None
    if not isinstance(info, dict):
        info = {}
    code = info.get("error_code") or ""
    text = str(info.get("msg") or info.get("error_description") or "").lower()

    if code == "invalid_credentials" or "invalid login credentials" in text:
        return "Email sau parolă greșită."
    if code == "email_not_confirmed" or "email not confirmed" in text:
        return ("Adresa de email nu este confirmată încă. Deschideți linkul "
                "din emailul de confirmare, apoi încercați din nou.")
    if status == 429:
        return "Prea multe încercări. Așteptați câteva minute și încercați din nou."
    return f"Serverul de conturi a refuzat cererea (eroarea {status})."


def _post(path: str, body: dict | None = None, token: str | None = None) -> dict:
    """POST to Supabase Auth and return the decoded JSON answer.

    Raises AuthOffline for transport trouble and 5xx (worth retrying later),
    AuthError for a 4xx verdict (retrying would get the same answer).
    """
    if not SUPABASE_URL:
        raise AuthOffline("Serverul de conturi nu este configurat în această "
                          "versiune a aplicației.")
    headers = {"apikey": SUPABASE_PUBLISHABLE_KEY,
               "Content-Type": "application/json",
               "User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{SUPABASE_URL}/auth/v1{path}",
                                 data=json.dumps(body or {}).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            raise AuthOffline(_MSG_OFFLINE) from exc
        raise AuthError(_error_message(exc.code, exc.read())) from exc
    except OSError as exc:  # URLError, timeout, connection reset…
        raise AuthOffline(_MSG_OFFLINE) from exc

    try:
        return json.loads(raw) if raw else {}
    except ValueError as exc:
        raise AuthOffline("Răspuns neașteptat de la serverul de conturi.") from exc


def _start_session(answer: dict) -> None:
    """Adopt the tokens from a successful sign-in or renewal."""
    global _access_token, _expires_at
    if "access_token" not in answer or "refresh_token" not in answer:
        raise AuthOffline("Răspuns neașteptat de la serverul de conturi.")
    _access_token = answer["access_token"]
    _expires_at = time.monotonic() + int(answer.get("expires_in", 3600))
    _save_refresh_token(answer["refresh_token"])


def has_session() -> bool:
    """True when a session is stored on this PC. It may still turn out to be
    expired: only `refresh` can tell, and only when online."""
    return _access_token is not None or _load_refresh_token() is not None


def sign_in(email: str, password: str) -> None:
    """Start a session from the user's credentials and remember it.

    Raises AuthError with the reason (wrong password, email not confirmed…)
    or AuthOffline when the server cannot be reached.
    """
    answer = _post("/token?grant_type=password",
                   {"email": email.strip(), "password": password})
    with _lock:
        _start_session(answer)


def refresh() -> None:
    """Renew the session from the stored refresh token.

    AuthOffline leaves everything as it was, so the app can carry on with the
    cached license. AuthError means the session is over (signed out on the
    website, password changed, token revoked): the stored token is dropped and
    the user has to sign in again.
    """
    with _lock:
        _refresh_locked()


def _refresh_locked() -> None:
    global _access_token
    stored = _load_refresh_token()
    if stored is None:
        _access_token = None
        raise AuthError(_MSG_SIGNED_OUT)
    try:
        answer = _post("/token?grant_type=refresh_token", {"refresh_token": stored})
    except AuthOffline:
        raise
    except AuthError as exc:
        _access_token = None
        _forget_refresh_token()
        raise AuthError(_MSG_EXPIRED) from exc
    _start_session(answer)


def access_token() -> str:
    """A valid access token for the license API, renewed first when missing
    or about to expire. Raises like `refresh`."""
    with _lock:
        if _access_token is None or time.monotonic() > _expires_at - _EXPIRY_MARGIN_S:
            _refresh_locked()
        return _access_token


def sign_out() -> None:
    """End the session on this PC.

    The local session is cleared first, so signing out always works, even
    offline. The server is then told on a best-effort basis; `scope=local`
    ends only this PC's session, not the account's other devices. Blocks for
    up to the network timeout, so call it off the UI thread.
    """
    global _access_token
    with _lock:
        token = _access_token
        _access_token = None
        _forget_refresh_token()
    if token:
        try:
            _post("/logout?scope=local", token=token)
        except AuthError:
            pass
