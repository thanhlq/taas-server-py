# eWorkSuite Identity Platform — OAuth 2.0 / OIDC Complete Guide

**Document Version:** 1.0
**Date:** April 10, 2026
**Status:** Living Document
**Audience:** Backend engineers implementing or replacing the IAM layer

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Service Naming Convention](#2-service-naming-convention)
3. [Authentication Methods & Flows](#3-authentication-methods--flows)
   - 3.1 Password
   - 3.2 TOTP (Time-based OTP)
   - 3.3 Passkey (WebAuthn / FIDO2)
4. [All Required OAuth 2.0 / OIDC Endpoints](#4-all-required-oauth-20--oidc-endpoints)
5. [Keycloak Admin API Mapping](#5-keycloak-admin-api-mapping)
6. [Phase-by-Phase Implementation Roadmap](#6-phase-by-phase-implementation-roadmap)
7. [Provider Swap Guide](#7-provider-swap-guide)
8. [Token Validation Checklist](#8-token-validation-checklist)
9. [Security Hardening](#9-security-hardening)

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                        │
│  @auth/nextjs  ←→  /api/auth/* (OIDC Authorization Code)  │
└─────────────────────────┬──────────────────────────────────┘
                          │ Bearer JWT (access_token)
┌─────────────────────────▼──────────────────────────────────┐
│  API Gateway / ews_api (FastAPI)                           │
│  ┌────────────────────────────────────────────────────┐   │
│  │  JWTMiddleware — validate RS256, iss, aud, exp     │   │
│  └──────────┬─────────────────────────────────────────┘   │
│             │                                              │
│  /auth/*    │  IamProviderFactory → IIamService            │
│             │         ↓                                    │
│             │  KeycloakIamService (current)                │
│             │  CognitoIamService  (future)                 │
│             │  AzureAdIamService  (future)                 │
└─────────────┼──────────────────────────────────────────────┘
              │ python-keycloak (Admin API + OpenID)
┌─────────────▼──────────────────────────────────────────────┐
│  Keycloak (internal IdP)                                   │
│  Realm per tenant (SaaS subdomain mapping)                 │
│  Flows: Password · TOTP · WebAuthn (Passkey)               │
└────────────────────────────────────────────────────────────┘
              │ SAML / OIDC federation (enterprise customers)
         External IdP (ADFS, Google Workspace, Okta…)
```

**Design principle:** Your application only talks to `IIamService`. Keycloak is an implementation detail — swapping it means writing a new class that implements the same interface, not touching endpoint or business logic code.

---

## 2. Service Naming Convention

### Python modules / classes

| Layer | Name | Location |
|---|---|---|
| Abstract interface | `IIamService` | `core/iam/types.py` |
| Provider factory | `IamProviderFactory` | `core/iam/provider_factory.py` |
| Keycloak implementation | `KeycloakIamService` | `iam_keycloak/services/kc_iam_service.py` |
| Future Cognito impl | `CognitoIamService` | `iam_cognito/services/cognito_iam_service.py` |
| Future Azure AD impl | `AzureAdIamService` | `iam_azure_ad/services/azure_ad_iam_service.py` |
| Middleware (FastAPI) | `JWTAuthBackend` | `iam_keycloak/adapter/keycloak_starlette_middleware.py` |

### HTTP routers (FastAPI APIRouter prefix)

| Router | Prefix | Purpose |
|---|---|---|
| Auth public | `/auth` | Login, register, token, passkey |
| Current user | `/me` | Self-service profile, MFA setup |
| Admin | `/admin` | User management (admin only) |
| OAuth2 callbacks | `/oauth2` | Social provider callbacks |
| WebAuthn | `/auth/passkey` | Passkey registration & assertion |

### Keycloak python-keycloak clients

| Variable | Class | Purpose |
|---|---|---|
| `keycloak_openid` | `KeycloakOpenID` | End-user token operations |
| `keycloak_admin` | `KeycloakAdmin` (via `KeycloakServerAdmin`) | Realm & user management |

---

## 3. Authentication Methods & Flows

### 3.1 Password (Resource Owner → Authorization Code)

**Client-side flow (SPA/mobile) — Authorization Code + PKCE**

```
1. Frontend generates code_verifier + code_challenge (S256)
2. GET /oauth2/authorize?
       client_id=eworksuite-app
       &response_type=code
       &redirect_uri=https://app.example.com/oauth2/callback
       &scope=openid profile email
       &code_challenge=<SHA256(verifier)>
       &code_challenge_method=S256
       &state=<csrf-token>
3. User enters password at Keycloak login page (or your custom page)
4. Keycloak → redirect to redirect_uri?code=AUTH_CODE&state=<same>
5. Backend POST /oauth2/token
       grant_type=authorization_code
       &code=AUTH_CODE
       &redirect_uri=...
       &code_verifier=<original>
       &client_id=eworksuite-app
6. Response: { access_token, id_token, refresh_token, expires_in }
```

**IIamService method:** `authenticate_password(login_form, context) → AuthResponse`
**Keycloak python-keycloak:** `keycloak_openid.token(username, password)`
**Preferred for:** Next.js app (via `@auth/nextjs` with Keycloak provider)

> **Never expose Resource Owner Password Credentials (ROPC)** to the frontend — it bypasses MFA and SSO. ROPC is only acceptable as a temporary bridge for legacy integrations.

---

### 3.2 TOTP (Time-Based One-Time Password)

TOTP adds a second factor after successful password verification.

**Enrollment flow**

```
1. POST /me/mfa/totp/setup
       → IIamService.enable_totp(user_id)
       → Keycloak: admin.set_totp(user_id) or send required action CONFIGURE_TOTP
       ← { secret, otpauth_uri, qr_code_svg }

2. User scans QR with Google Authenticator / Authy / etc.

3. POST /me/mfa/totp/verify
       body: { totp_code: "123456" }
       → IIamService.verify_totp(user_id, totp_code)
       → keycloak_openid.token(..., totp=totp_code)   # confirms enrollment
       ← 200 OK — TOTP activated
```

**Login flow with TOTP**

```
1. POST /auth/token  { username, password }
   ← 401  { mfa_required: true, mfa_token: "<short-lived session token>" }

2. POST /auth/token/mfa  { mfa_token, totp_code }
   → keycloak_openid.token(username, password, totp=totp_code)
   ← { access_token, id_token, refresh_token }
```

**IIamService methods:**
- `enable_totp(user_id) → { secret, qr_code_svg }`
- `verify_totp(user_id, totp_code) → bool`
- `disable_totp(user_id) → bool`
- `get_totp_backup_codes(user_id) → List[str]`

**Keycloak Admin API:**
```python
# Require TOTP setup on next login
keycloak_admin.set_user(user_id, {"requiredActions": ["CONFIGURE_TOTP"]})

# Check if TOTP enabled
user = keycloak_admin.get_user(user_id)
totp_enabled = user.get("totp", False)

# Remove TOTP credentials (disable)
credentials = keycloak_admin.get_credentials(user_id)
totp_creds = [c for c in credentials if c["type"] == "otp"]
for c in totp_creds:
    keycloak_admin.delete_credential(user_id, c["id"])
```

---

### 3.3 Passkey (WebAuthn / FIDO2)

Passkeys replace passwords entirely. The browser/OS generates a public-private key pair bound to your domain.

**Prerequisites in Keycloak:**
- Enable `WebAuthn Authenticator` credential provider in realm
- Set Relying Party (RP) ID = your domain (e.g., `app.example.com`)
- Enable `WebAuthn Passwordless Policy` for passwordless login

**Passkey Registration (enrollment)**

```
1. POST /auth/passkey/register/begin
       → IIamService.passkey_register_begin(user_id)
       → keycloak_admin.set_user(user_id,
             {"requiredActions": ["webauthn-register"]})
         OR call Keycloak WebAuthn registration API directly
       ← { challenge, rp, user, pubKeyCredParams, ... }  # PublicKeyCredentialCreationOptions

2. Browser: navigator.credentials.create({ publicKey: options })
       ← { id, rawId, response: { attestationObject, clientDataJSON }, type }

3. POST /auth/passkey/register/complete
       body: { credential: <WebAuthn response> }
       → IIamService.passkey_register_complete(user_id, credential)
       → keycloak_admin stores credential
       ← 200 OK — passkey registered
```

**Passkey Authentication (login)**

```
1. POST /auth/passkey/authenticate/begin
       body: { username_or_email }   (optional — allows "usernameless" flow)
       → IIamService.passkey_authenticate_begin(username_or_email?)
       ← { challenge, allowCredentials, timeout, rpId }  # PublicKeyCredentialRequestOptions

2. Browser: navigator.credentials.get({ publicKey: options })
       ← { id, rawId, response: { authenticatorData, signature, clientDataJSON }, type }

3. POST /auth/passkey/authenticate/complete
       body: { credential: <WebAuthn response> }
       → IIamService.passkey_authenticate_complete(credential)
       → keycloak_openid verifies assertion
       ← { access_token, id_token, refresh_token }
```

**IIamService methods to add:**
- `passkey_register_begin(user_id) → PublicKeyCredentialCreationOptions`
- `passkey_register_complete(user_id, credential) → bool`
- `passkey_authenticate_begin(username?) → PublicKeyCredentialRequestOptions`
- `passkey_authenticate_complete(credential) → AuthResponse`
- `list_passkeys(user_id) → List[PasskeyInfo]`
- `delete_passkey(user_id, credential_id) → bool`

**Keycloak Admin API for passkeys:**
```python
# List WebAuthn credentials for a user
credentials = keycloak_admin.get_credentials(user_id)
webauthn_creds = [c for c in credentials if c["type"] == "webauthn"]

# Delete a specific passkey
keycloak_admin.delete_credential(user_id, credential_id)

# Required action to trigger WebAuthn registration
keycloak_admin.set_user(user_id, {
    "requiredActions": ["webauthn-register-passwordless"]
})
```

---

## 4. All Required OAuth 2.0 / OIDC Endpoints

### 4.1 Standard OIDC Discovery (Keycloak provides these)

These are **Keycloak's own endpoints** — you do not implement them; you consume them.

```
GET /.well-known/openid-configuration
    → Discover all endpoints below automatically
```

| Endpoint | URL pattern | Purpose |
|---|---|---|
| Authorization | `/realms/{realm}/protocol/openid-connect/auth` | Start Authorization Code flow |
| Token | `/realms/{realm}/protocol/openid-connect/token` | Exchange code → tokens |
| UserInfo | `/realms/{realm}/protocol/openid-connect/userinfo` | Get user claims |
| JWKS | `/realms/{realm}/protocol/openid-connect/certs` | Public keys for JWT verification |
| Introspection | `/realms/{realm}/protocol/openid-connect/token/introspect` | Validate opaque token |
| Revocation | `/realms/{realm}/protocol/openid-connect/revoke` | Revoke access/refresh token |
| Logout | `/realms/{realm}/protocol/openid-connect/logout` | End session |

### 4.2 Your Application Endpoints (FastAPI)

These are the endpoints **your app exposes** — they either proxy Keycloak or add business logic on top.

#### Public Auth (`/auth`)

| Method | Path | IIamService method | Notes |
|---|---|---|---|
| `POST` | `/auth/signup/verification/email` | `signup_send_otp_to_email` | Step 1: check email + send OTP |
| `POST` | `/auth/signup` | `create_directory_user` | Step 2: register user |
| `POST` | `/auth/signup/verify` | `verify_email` | Step 3: verify OTP / email link |
| `POST` | `/auth/token` | `authenticate_password` | Password login → tokens |
| `POST` | `/auth/token/refresh` | `refresh_token` | Rotate refresh token |
| `POST` | `/auth/token/revoke` | `revoke_token` | Revoke token |
| `POST` | `/auth/token/mfa` | `authenticate_otp` | Submit TOTP code after password |
| `POST` | `/auth/logout` | `logout` | End session, revoke tokens |
| `GET` | `/auth/oauth2/{provider}` | `authenticate_social` | Social login redirect |
| `GET` | `/auth/oauth2/{provider}/callback` | `authenticate_social` | Social login callback |
| `POST` | `/auth/password/reset` | `send_password_reset_email` | Forgot password |
| `POST` | `/auth/password/reset/verify` | `verify_password_reset_token` | Verify reset token |
| `POST` | `/auth/password/reset/complete` | `complete_password_reset` | Set new password |
| `POST` | `/auth/passkey/register/begin` | `passkey_register_begin` | WebAuthn registration options |
| `POST` | `/auth/passkey/register/complete` | `passkey_register_complete` | Store WebAuthn credential |
| `POST` | `/auth/passkey/authenticate/begin` | `passkey_authenticate_begin` | WebAuthn assertion options |
| `POST` | `/auth/passkey/authenticate/complete` | `passkey_authenticate_complete` | Verify assertion → tokens |

#### Current User (`/me`)

| Method | Path | IIamService method | Notes |
|---|---|---|---|
| `GET` | `/me` | `get_user_profile` | Get own profile + claims |
| `PUT` | `/me` | `update_user_profile` | Update display name, locale, etc. |
| `PUT` | `/me/password` | `change_password` | Change own password |
| `GET` | `/me/sessions` | `get_user_sessions` | List active sessions |
| `DELETE` | `/me/sessions/{session_id}` | `revoke_session` | Revoke specific session |
| `DELETE` | `/me/sessions` | `revoke_all_sessions` | Sign out everywhere |
| `GET` | `/me/mfa` | `get_mfa_status` | Check TOTP + passkey status |
| `POST` | `/me/mfa/totp/setup` | `enable_totp` | Get QR code / secret |
| `POST` | `/me/mfa/totp/verify` | `verify_totp` | Confirm enrollment |
| `DELETE` | `/me/mfa/totp` | `disable_totp` | Remove TOTP |
| `GET` | `/me/mfa/totp/backup-codes` | `get_totp_backup_codes` | One-time recovery codes |
| `GET` | `/me/passkeys` | `list_passkeys` | List registered passkeys |
| `DELETE` | `/me/passkeys/{credential_id}` | `delete_passkey` | Remove a passkey |

#### Admin (`/admin`)

| Method | Path | IIamService method | Notes |
|---|---|---|---|
| `GET` | `/admin/users` | `list_users` | Paginated user list |
| `GET` | `/admin/users/:id` | `get_user` | User detail |
| `POST` | `/admin/users` | `create_user` (admin invite) | Admin-provisioned user |
| `PUT` | `/admin/users/:id` | `update_user` | Edit user attributes |
| `DELETE` | `/admin/users/:id` | `delete_user` | Hard delete |
| `POST` | `/admin/users/:id/disable` | `disable_user` | Soft disable |
| `POST` | `/admin/users/:id/enable` | `enable_user` | Re-enable |
| `POST` | `/admin/users/:id/reset-password` | `admin_reset_password` | Force reset |
| `GET` | `/admin/users/:id/sessions` | `get_user_sessions` | All sessions for user |
| `DELETE` | `/admin/users/:id/sessions` | `revoke_all_sessions` | Force logout user |
| `GET` | `/admin/realms` | `list_realms` | Tenant realm list |
| `POST` | `/admin/realms` | `create_realm` | Provision new tenant (SaaS) |
| `PUT` | `/admin/realms/:realm` | `update_realm` | Realm configuration |

---

## 5. Keycloak Admin API Mapping

Using `python-keycloak` (`KeycloakAdmin` + `KeycloakOpenID`).

### 5.1 User lifecycle

```python
from keycloak import KeycloakAdmin, KeycloakOpenID

# ── Registration ──────────────────────────────────────────
user_id = keycloak_admin.create_user({
    "username": email,
    "email": email,
    "firstName": first_name,
    "lastName": last_name,
    "enabled": True,
    "emailVerified": False,
    "credentials": [{"type": "password", "value": password, "temporary": False}],
    "requiredActions": ["VERIFY_EMAIL"],
    "attributes": {"tenant_id": [tenant_id]},
})

# ── Email verification (send action email) ────────────────
keycloak_admin.send_verify_email(user_id)
# or programmatic OTP (current approach): cache OTP, send via mailer

# ── Get user ──────────────────────────────────────────────
user = keycloak_admin.get_user(user_id)
users = keycloak_admin.get_users({"email": email, "exact": True})

# ── Update user ───────────────────────────────────────────
keycloak_admin.update_user(user_id, {"firstName": "New Name"})

# ── Disable / enable ──────────────────────────────────────
keycloak_admin.update_user(user_id, {"enabled": False})
keycloak_admin.update_user(user_id, {"enabled": True})

# ── Delete user ───────────────────────────────────────────
keycloak_admin.delete_user(user_id)

# ── Force password reset ──────────────────────────────────
keycloak_admin.set_user_password(user_id, new_password, temporary=False)
keycloak_admin.send_update_account(user_id, ["UPDATE_PASSWORD"])
```

### 5.2 Authentication / Tokens

```python
# ── Password login (OpenID token endpoint) ────────────────
token = keycloak_openid.token(username, password)
# token = { access_token, refresh_token, id_token, expires_in, ... }

# ── Password + TOTP ───────────────────────────────────────
token = keycloak_openid.token(username, password, totp=totp_code)

# ── Refresh ───────────────────────────────────────────────
token = keycloak_openid.refresh_token(refresh_token)

# ── Introspect (validate opaque or JWT) ───────────────────
info = keycloak_openid.introspect(token["access_token"])
assert info["active"] is True

# ── Decode + verify JWT locally (preferred for hot paths) ─
public_key = keycloak_openid.public_key()
claims = keycloak_openid.decode_token(
    token["access_token"],
    key=f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----",
    options={"verify_aud": False},
)

# ── Logout ────────────────────────────────────────────────
keycloak_openid.logout(refresh_token)

# ── Revoke specific token ─────────────────────────────────
keycloak_openid.revoke_token(access_token, token_type_hint="access_token")
```

### 5.3 TOTP management

```python
# Check TOTP status
user = keycloak_admin.get_user(user_id)
totp_active = user.get("totp", False)

# Require TOTP configure on next login
keycloak_admin.update_user(user_id, {"requiredActions": ["CONFIGURE_TOTP"]})

# Get OTP credentials
credentials = keycloak_admin.get_credentials(user_id)
otp_creds = [c for c in credentials if c["type"] == "otp"]

# Remove TOTP
for c in otp_creds:
    keycloak_admin.delete_credential(user_id, c["id"])
```

### 5.4 Passkey (WebAuthn) management

```python
# List WebAuthn credentials
credentials = keycloak_admin.get_credentials(user_id)
passkeys = [c for c in credentials if "webauthn" in c["type"]]

# Rename passkey label (user-visible name)
keycloak_admin.update_credential(user_id, credential_id, {"userLabel": "MacBook Touch ID"})

# Delete passkey
keycloak_admin.delete_credential(user_id, credential_id)

# Trigger WebAuthn registration via required action
keycloak_admin.update_user(user_id, {
    "requiredActions": ["webauthn-register"]           # password + passkey
    # "requiredActions": ["webauthn-register-passwordless"]  # pure passkey
})
```

### 5.5 Session management

```python
# List sessions for a user
sessions = keycloak_admin.get_sessions(user_id)

# Get realm-wide sessions
sessions = keycloak_admin.get_realm_sessions(first=0, max=100)

# Revoke all sessions for a user (force logout)
keycloak_admin.delete_sessions(user_id)  # invalidates all tokens

# Realm-level logout (all users)
keycloak_admin.delete_all_realm_sessions()
```

### 5.6 SaaS realm per tenant

```python
# Create tenant realm
keycloak_admin.create_realm({
    "realm": f"tenant-{tenant_slug}",
    "displayName": tenant_display_name,
    "enabled": True,
    "sslRequired": "external",
    "registrationAllowed": False,
    "loginTheme": "eworksuite",
    "accountTheme": "eworksuite",
    "smtpServer": { ... },
})

# Switch admin context to tenant realm
keycloak_admin.change_current_realm(f"tenant-{tenant_slug}")

# Delete tenant realm (destructive — triggers all user logout)
keycloak_admin.delete_realm(f"tenant-{tenant_slug}")
```

---

## 6. Phase-by-Phase Implementation Roadmap

### Phase 0 — Hardening (current state, 1 week)

Goal: make existing Keycloak integration production-ready.

- [ ] Replace all ROPC (`token(username, password)`) in frontend with Authorization Code + PKCE
- [ ] JWT validation middleware: verify `iss`, `aud`, `exp`, `nbf`, signature (RS256 via JWKS)
- [ ] Cache JWKS with TTL (avoid fetching on every request)
- [ ] Refresh token rotation enabled in Keycloak (`Refresh Token Max Reuse = 0`)
- [ ] Enable brute-force protection in Keycloak realm settings
- [ ] Add `check_user_signin_lockout` to all login paths (already partially done)

### Phase 1 — Complete IIamService interface (2 weeks)

Goal: every method in `IIamService` has a real `KeycloakIamService` implementation.

- [ ] All `/me` endpoints implemented and wired
- [ ] TOTP: `enable_totp`, `verify_totp`, `disable_totp`, `get_totp_backup_codes`
- [ ] Session management: `get_user_sessions`, `revoke_session`, `revoke_all_sessions`
- [ ] Password management: full flow tested end-to-end
- [ ] Social login: Google + Microsoft callbacks working
- [ ] Integration tests for every `IIamService` method against real Keycloak

### Phase 2 — Passkey (WebAuthn) (2 weeks)

Goal: users can register and log in with passkeys.

- [ ] Enable WebAuthn in Keycloak realm (`webauthn-authenticator`, `webauthn-passwordless-authenticator`)
- [ ] Implement `passkey_register_begin/complete` in `KeycloakIamService`
- [ ] Implement `passkey_authenticate_begin/complete`
- [ ] Frontend: integrate `SimpleWebAuthn` (`@simplewebauthn/browser`)
- [ ] `/me/passkeys` CRUD endpoints
- [ ] Support "conditional mediation" (browser auto-fills passkey during sign-in)

### Phase 3 — Provider Abstraction Verification (1 week)

Goal: prove the interface is truly provider-agnostic.

- [ ] Write a `MockIamService` implementing `IIamService` using in-memory storage
- [ ] All endpoint tests pass against `MockIamService` (no Keycloak dependency)
- [ ] Document config keys needed by each `IamProvider` variant
- [ ] `IamProviderFactory.create(IamProvider.AWS_COGNITO, config)` returns a stub that passes type checking

### Phase 4 — Enterprise SSO / SAML Federation (as needed)

Goal: enterprise customers can bring their own IdP.

- [ ] Keycloak configured as SAML SP → enterprise IdP (ADFS, Azure AD, Okta)
- [ ] OIDC federation alternative (for IdPs that support OIDC)
- [ ] `/admin/realms/:realm/idp` endpoint to configure external IdP per tenant
- [ ] JIT (Just-in-Time) user provisioning on first SSO login
- [ ] Attribute mapping: external claims → local user attributes

### Phase 5 — Provider Swap Dry Run (future)

Goal: validate that swapping Keycloak → Cognito is viable.

- [ ] Implement `CognitoIamService` (or `AutheliaIamService`) for non-prod env
- [ ] Run integration test suite against both providers
- [ ] Document migration path for existing user credentials (password hash export is Keycloak-specific)

---

## 7. Provider Swap Guide

When you swap Keycloak for another provider, the contract is `IIamService`. Here is what changes and what does not.

### What stays the same (provider-agnostic)

- All FastAPI routers (`/auth`, `/me`, `/admin`)
- All request/response schemas (`PasswordAuthRequest`, `AuthResponse`, etc.)
- JWT validation logic — just update `JWKS_URI` and `ISSUER` in config
- Business logic (OTP generation, email templates, signin lockout)
- `IamProviderFactory` dispatcher

### What changes per provider

| Concern | Keycloak | AWS Cognito | Azure AD B2C | Authelia |
|---|---|---|---|---|
| User creation | `keycloak_admin.create_user(...)` | `cognito.admin_create_user(...)` | Graph API `POST /users` | REST API |
| Token endpoint | `/openid-connect/token` | Cognito hosted UI | `/oauth2/v2.0/token` | `/api/oidc/token` |
| TOTP enable | `set_user(requiredActions=CONFIGURE_TOTP)` | `associate_software_token` | Conditional Access policy | TOTP config |
| Passkey | `webauthn-register` required action | Cognito Passkey (preview) | FIDO2 via Azure MFA | WebAuthn built-in |
| Admin SDK | `python-keycloak` | `boto3.client('cognito-idp')` | `msal` + Graph SDK | REST only |
| Realm/tenant | One realm per tenant | One User Pool per tenant | One B2C tenant | One instance |

### Config keys to abstract

```toml
# config/base.toml — provider-agnostic keys
[iam]
provider = "keycloak"            # keycloak | aws_cognito | azure_ad | authelia
issuer = "https://..."           # OIDC iss claim
jwks_uri = "https://.../certs"
token_endpoint = "https://.../token"
userinfo_endpoint = "https://.../userinfo"
client_id = ""
client_secret = ""               # store in secrets/

# Keycloak-specific (ignored by other providers)
[iam.keycloak]
server_url = "http://keycloak:8080"
realm = "eworksuite"
admin_username = ""
admin_password = ""              # store in secrets/
```

---

## 8. Token Validation Checklist

Every protected FastAPI endpoint validates the Bearer JWT. The middleware must check:

```python
# Pseudo-code for JWTAuthBackend
async def authenticate(self, request):
    token = find_bearer_token(request)
    if not token:
        return UnauthenticatedUser(), []

    # 1. Fetch JWKS (cached — refresh on kid miss)
    jwks = await fetch_jwks(settings.IAM_JWKS_URI)

    # 2. Decode header to get kid
    header = jwt.get_unverified_header(token)

    # 3. Find matching key
    key = find_key(jwks, header["kid"])

    # 4. Verify signature + claims
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],       # never "none" or "HS256" for Keycloak
        audience=settings.IAM_CLIENT_ID,
        issuer=settings.IAM_ISSUER,
        options={
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iss": True,
            "verify_aud": True,
        }
    )

    # 5. Check token type — reject id_tokens used as access tokens
    assert claims.get("typ") in ("Bearer", "JWT")

    return AuthenticatedUser(claims), scopes_from(claims)
```

---

## 9. Security Hardening

### Keycloak Realm settings to enable

| Setting | Value | Reason |
|---|---|---|
| Access Token Lifespan | 5 min | Short-lived; rotate via refresh |
| Refresh Token Lifespan | 30 min (web), 30 days (offline) | Balance UX vs security |
| Refresh Token Max Reuse | 0 | Single-use refresh tokens |
| Revoke Refresh Token | On | Invalidate family on reuse |
| Brute Force Protection | On | Lock account after N failures |
| Max Login Failures | 5 | Before temporary lockout |
| Wait Increment | 60 sec | Lockout duration |
| SSL Required | All | Never HTTP in prod |
| Content-Security-Policy | Strict | XSS protection on login page |

### Application-level

- Store `refresh_token` in `HttpOnly; Secure; SameSite=Strict` cookie — never in `localStorage`
- Store `access_token` in memory only (not localStorage, not sessionStorage)
- Implement PKCE for all public clients (SPA, mobile)
- Rotate refresh tokens on every use
- Emit `iam.login`, `iam.logout`, `iam.mfa.enabled` audit events to the event bus
- Rate-limit `/auth/token`, `/auth/password/reset` endpoints (e.g., 5 req/min per IP)
- Validate `state` parameter on OAuth2 callbacks (CSRF protection)
- Validate `redirect_uri` is an exact match to pre-registered URIs (no wildcards)
