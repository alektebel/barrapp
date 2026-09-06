"""Email + password accounts, so training history outlives a phone.

Cognito holds the credentials. Nothing here hashes, stores or compares a
password: that is the one part of auth worth handing to a service that has
already thought about salting, rotation, throttling and lockout.

The phone never talks to Cognito directly and never carries the AWS SDK - it
posts email and password to this API, which proxies to Cognito and hands back
the tokens. That keeps the Android side to plain HTTP and keeps the app's
client id server-side.

Identity, before and after:

    X-Device-Id: <uuid>       ->  owner = "<uuid>"       (anonymous, still works)
    Authorization: Bearer ... ->  owner = "u:<cognito sub>"

Both forms coexist on purpose. An install that predates accounts keeps working
untouched, and `claim` is what moves that anonymous history onto an account.
"""
from __future__ import annotations

import hashlib
import os
import time

import boto3
from botocore.exceptions import ClientError

cognito = boto3.client("cognito-idp")

POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("USER_POOL_CLIENT_ID", "")

# Verifying an access token means asking Cognito. The phone polls a running
# job every few seconds, so the same token is presented over and over; without
# this cache each poll would spend a Cognito round trip proving the same thing.
# Keyed by a hash so a raw token is never held in memory longer than the call.
_VERIFY_TTL = 300
_verified: dict[str, tuple[float, str, str]] = {}


class AuthError(Exception):
    """Something the caller should see as 4xx, with a sentence they can act on."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(POOL_ID and CLIENT_ID)


def _require_config() -> None:
    if not configured():
        raise AuthError("accounts are not enabled on this server", 501)


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- the endpoints -----------------------------------------------------

def signup(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if "@" not in email:
        raise AuthError("that does not look like an email address")
    if len(password) < 8:
        raise AuthError("use at least 8 characters")
    try:
        cognito.sign_up(
            ClientId=CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
    except ClientError as err:
        raise _translate(err) from err
    return {"email": email, "needsConfirmation": True}


def confirm(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()
    try:
        cognito.confirm_sign_up(ClientId=CLIENT_ID, Username=email, ConfirmationCode=code)
    except ClientError as err:
        raise _translate(err) from err
    return {"email": email, "confirmed": True}


def resend(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    try:
        cognito.resend_confirmation_code(ClientId=CLIENT_ID, Username=email)
    except ClientError as err:
        raise _translate(err) from err
    return {"email": email, "sent": True}


def login(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    try:
        out = cognito.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except ClientError as err:
        raise _translate(err) from err
    result = out.get("AuthenticationResult") or {}
    if not result.get("AccessToken"):
        # A challenge (new password required, MFA). Nothing in this app sets
        # one up, so say so plainly rather than returning a half-login.
        raise AuthError("this account needs to be finished in the console", 409)
    return _tokens(result)


def refresh(body: dict) -> dict:
    _require_config()
    token = body.get("refreshToken") or ""
    try:
        out = cognito.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": token},
        )
    except ClientError as err:
        raise _translate(err) from err
    return _tokens(out.get("AuthenticationResult") or {})


def forgot(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    try:
        cognito.forgot_password(ClientId=CLIENT_ID, Username=email)
    except ClientError as err:
        raise _translate(err) from err
    return {"email": email, "sent": True}


def reset(body: dict) -> dict:
    _require_config()
    email = (body.get("email") or "").strip().lower()
    try:
        cognito.confirm_forgot_password(
            ClientId=CLIENT_ID,
            Username=email,
            ConfirmationCode=(body.get("code") or "").strip(),
            Password=body.get("password") or "",
        )
    except ClientError as err:
        raise _translate(err) from err
    return {"email": email, "reset": True}


def _tokens(result: dict) -> dict:
    out = {
        "accessToken": result.get("AccessToken", ""),
        "expiresIn": result.get("ExpiresIn", 3600),
    }
    # Absent on a refresh: the old refresh token stays valid, so the phone
    # keeps the one it has rather than clearing it.
    if result.get("RefreshToken"):
        out["refreshToken"] = result["RefreshToken"]
    return out


# ---- who is calling ----------------------------------------------------

def identify(token: str) -> tuple[str, str]:
    """(owner, email) for a bearer access token. Raises AuthError if it is not
    valid - expired, revoked, or simply not ours."""
    _require_config()
    now = time.time()
    key = _key(token)
    hit = _verified.get(key)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        user = cognito.get_user(AccessToken=token)
    except ClientError as err:
        raise AuthError("sign in again", 401) from err
    attrs = {a["Name"]: a["Value"] for a in user.get("UserAttributes") or []}
    sub = attrs.get("sub") or user.get("Username") or ""
    if not sub:
        raise AuthError("sign in again", 401)
    owner, email = f"u:{sub}", attrs.get("email", "")
    if len(_verified) > 512:
        _verified.clear()
    _verified[key] = (now + _VERIFY_TTL, owner, email)
    return owner, email


def _translate(err: ClientError) -> AuthError:
    """Cognito's codes, as sentences. The message reaches a person on a phone,
    so it says what to do rather than naming the exception."""
    code = err.response.get("Error", {}).get("Code", "")
    return {
        "UsernameExistsException": AuthError("that email already has an account", 409),
        "NotAuthorizedException": AuthError("wrong email or password", 401),
        "UserNotFoundException": AuthError("wrong email or password", 401),
        "UserNotConfirmedException": AuthError(
            "check your email for the confirmation code", 403),
        "CodeMismatchException": AuthError("that code is not right"),
        "ExpiredCodeException": AuthError("that code has expired - ask for a new one"),
        "InvalidPasswordException": AuthError(
            "use at least 8 characters, with a letter and a number"),
        "InvalidParameterException": AuthError("check the email and password"),
        "LimitExceededException": AuthError("too many tries - wait a minute", 429),
        "TooManyRequestsException": AuthError("too many tries - wait a minute", 429),
    }.get(code, AuthError(f"could not complete that ({code or 'unknown error'})", 400))
