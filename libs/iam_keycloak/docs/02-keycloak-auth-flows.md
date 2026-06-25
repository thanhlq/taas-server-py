# Keycloak Authentication Flows - eWorkSuite IAM Implementation

**Document Version:** 1.0
**Last Updated:** November 29, 2025
**Status:** Production
**Related Specification:** [eWorkSuite IAM Service Specification](01-eworksuite-iam-service.md)

---

## Document Purpose

This document analyzes Keycloak authentication flows and maps them to the eWorkSuite IAM Service Specification requirements. It provides a concise guide on which flows to use for each authentication scenario.

**Input Documents:**
- Our IAM service specification: [eWorkSuite IAM Service](01-eworksuite-iam-service.md)
- [Keycloak Documentation](https://www.keycloak.org/documentation)

**Keycloak Realm:**
- **Realm Name:** `eworksuite`
- **Realm ID:** `c88daceb-412c-4b3a-9169-0c7909aaa636`
- **Keycloak Version:** 21.1.2

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Specification Coverage Matrix](#2-specification-coverage-matrix)
3. [OpenID Connect Flow Comparison](#3-openid-connect-flow-comparison)
4. [Standard Authentication Flows](#4-standard-authentication-flows)
5. [Custom Authentication Flows](#5-custom-authentication-flows)
6. [Flow Selection Guide](#6-flow-selection-guide)
7. [Implementation Examples](#7-implementation-examples)
8. [Security Recommendations](#8-security-recommendations)

---

## 1. Executive Summary

### 1.1 Supported Specification Requirements

The current Keycloak configuration supports the following requirements from the IAM specification:

| Spec Ref | Requirement | Status | Keycloak Flow |
|----------|-------------|--------|---------------|
| REQ-AUTH-001 | User Registration | ✅ Implemented | `registration` flow |
| REQ-AUTH-002 | User Login (Password/OTP/Social) | ✅ Implemented | `browser` + `direct grant` flows |
| REQ-AUTH-003 | Two-Factor Authentication (2FA/OTP) | ✅ Implemented | Conditional OTP in all flows |
| REQ-AUTH-004 | Password Management | ✅ Implemented | `reset credentials` flow |
| REQ-TOKEN-001 | Token Refresh | ✅ Implemented | OAuth2 refresh token flow |
| REQ-TOKEN-002 | Single Sign-On (SSO) | ✅ Implemented | `browser` flow with cookies |
| REQ-ADMIN-001 | Admin Impersonation | ✅ Implemented | Token exchange flow |
| REQ-ADMIN-002 | Service Account Auth | ✅ Implemented | Client credentials flow |

### 1.2 Flow Usage Summary

**Recommended Flow Mapping:**

```
┌───────────────────────────────────────────────────────────────────┐
│ Use Case                    │ OAuth2 Flow    │ Keycloak Flow      │
├─────────────────────────────┼────────────────┼────────────────────┤
│ 2.1.1 Registration          │ N/A            │ registration       │
│ 2.1.2.1 Password Login      │ Auth Code+PKCE │ browser            │
│ 2.1.2.2 OTP Login           │ Auth Code+PKCE │ browser            │
│ 2.1.2.3 Social Login        │ Auth Code+PKCE │ browser            │
│ 2.1.3 Two-Factor (2FA)      │ N/A (built-in) │ browser            │
│ 2.1.4 Password Reset        │ N/A            │ reset credentials  │
│ 2.2.1 Token Refresh         │ Refresh Token  │ N/A                │
│ 2.2.2 SSO                   │ Auth Code+PKCE │ browser            │
│ 2.3.1 Admin Impersonation   │ Token Exchange │ N/A                │
│ 2.3.2 Service Account       │ Client Creds   │ N/A                │
│ Legacy/Mobile (⚠️)          │ ROPC           │ direct grant       │
└───────────────────────────────────────────────────────────────────┘
```

### 1.3 Key Recommendations

**✅ Use for Production:**
1. **Authorization Code + PKCE** - Primary flow for web/mobile (REQ-AUTH-002)
2. **Browser Flow** - Handles password, OTP, social login (REQ-AUTH-002, REQ-AUTH-003)
3. **Registration Flow** - User signup (REQ-AUTH-001)
4. **Reset Credentials Flow** - Password recovery (REQ-AUTH-004)
5. **Client Credentials** - Service-to-service (REQ-ADMIN-002)

**⚠️ Use with Caution:**
- **Direct Grant (ROPC)** - Legacy/migration only, plan to migrate to Auth Code + PKCE

**❌ Do Not Use:**
- **Implicit Flow** - Deprecated, security risk

---

## 2. Specification Coverage Matrix

### 2.1 Authentication Methods Coverage

#### 2.1.1 User Registration (REQ-AUTH-001)

| Spec Requirement | Keycloak Implementation | Flow Used | Status |
|------------------|-------------------------|-----------|--------|
| 2.1.1.1 Email/password registration | ✅ Built-in | `registration` | Complete |
| 2.1.1.2 Social registration (Google, Microsoft) | ✅ Via IdP | `first broker login` | Complete |
| 2.1.1.3 Email verification workflow | ⚠️ Available but DISABLED | `registration` + email action | **Enable Required** |
| 2.1.1.4 User profile with custom attributes | ✅ Protocol mappers | `registration` | Complete |

**Keycloak Flow:** `registration`
**Action Required:** Enable email verification in realm settings

#### 2.1.2 User Login (REQ-AUTH-002)

| Spec Requirement | Keycloak Implementation | Flow Used | Status |
|------------------|-------------------------|-----------|--------|
| 2.1.2.1 Password-based authentication | ✅ Built-in | `browser` | Complete |
| 2.1.2.2 OTP-based authentication (passwordless) | ✅ Custom flow | `Direct Grant With OTP` | Complete |
| 2.1.2.3 Social login (Google, Microsoft) | ✅ Identity Providers | `browser` + IdP redirect | Complete |
| 2.1.2.4 Remember me (persistent sessions) | ✅ Built-in | `browser` | Complete |
| 2.1.2.5 Multi-protocol (OAuth2, OIDC) | ✅ Built-in | All flows | Complete |

**Keycloak Flows:** `browser` (primary), `direct grant` (API), `Direct Grant With OTP` (passwordless)

#### 2.1.3 Two-Factor Authentication (REQ-AUTH-003)

| Spec Requirement | Keycloak Implementation | Flow Used | Status |
|------------------|-------------------------|-----------|--------|
| 2.1.3.1 TOTP-based (Time-based OTP) | ✅ Built-in | Conditional OTP sub-flow | Complete |
| 2.1.3.2 Conditional OTP (if configured) | ✅ Built-in | All flows | Complete |
| 2.1.3.3 Compatible with Auth Code + PKCE | ✅ Built-in | `browser` flow | Complete |
| 2.1.3.4 QR code for authenticator apps | ✅ Built-in | Required action | Complete |

**Keycloak Flows:** Conditional OTP integrated in `browser`, `direct grant`, `reset credentials`

#### 2.1.4 Password Management (REQ-AUTH-004)

| Spec Requirement | Keycloak Implementation | Flow Used | Status |
|------------------|-------------------------|-----------|--------|
| 2.1.4.1 Email-based password reset | ✅ Built-in | `reset credentials` | Complete |
| 2.1.4.2 Forgot password workflow | ✅ Built-in | `reset credentials` | Complete |
| 2.1.4.3 Secure token with expiration | ✅ Built-in | `reset credentials` | Complete |
| 2.1.4.4 Password policy enforcement | ✅ Configured | Realm settings | Complete |

**Keycloak Flow:** `reset credentials`

### 2.2 Token & Session Management Coverage

#### 2.2.1 Token Refresh (REQ-TOKEN-001)

| Spec Requirement | Keycloak Implementation | OAuth2 Flow | Status |
|------------------|-------------------------|-------------|--------|
| 2.2.1.1 Automatic token refresh | ✅ OAuth2 standard | Refresh Token | Complete |
| 2.2.1.2 Refresh token rotation | ✅ Configured | Refresh Token | Complete |
| 2.2.1.3 Single-use refresh tokens | ✅ Configured | Refresh Token | Complete |
| 2.2.1.4 Offline access (30-day) | ✅ Configured | Refresh Token | Complete |

**OAuth2 Mechanism:** Standard refresh token flow, no custom Keycloak flow needed

#### 2.2.2 Single Sign-On (REQ-TOKEN-002)

| Spec Requirement | Keycloak Implementation | Flow Used | Status |
|------------------|-------------------------|-----------|--------|
| 2.2.2.1 Cross-application SSO | ✅ Built-in | `browser` with cookies | Complete |
| 2.2.2.2 SSO session management | ✅ Built-in | `browser` | Complete |
| 2.2.2.3 Remember me cookies | ✅ Built-in | `browser` | Complete |
| 2.2.2.4 Centralized logout | ✅ Built-in | OIDC logout endpoint | Complete |

**Keycloak Flow:** `browser` flow handles SSO automatically

### 2.3 Administrative Features Coverage

#### 2.3.1 Admin Impersonation (REQ-ADMIN-001)

| Spec Requirement | Keycloak Implementation | OAuth2 Flow | Status |
|------------------|-------------------------|-------------|--------|
| 2.3.1.1 Secure impersonation via token exchange | ✅ Built-in | Token Exchange | Complete |
| 2.3.1.2 Audit trail of impersonation | ✅ Keycloak events | N/A | Complete |
| 2.3.1.3 Limited to admin roles | ✅ Authorization policy | N/A | Complete |
| 2.3.1.4 Time-limited sessions | ✅ Token expiration | N/A | Complete |

**OAuth2 Flow:** Token Exchange (RFC 8693)
**Client:** `eworksuite_business`

#### 2.3.2 Service Account Authentication (REQ-ADMIN-002)

| Spec Requirement | Keycloak Implementation | OAuth2 Flow | Status |
|------------------|-------------------------|-------------|--------|
| 2.3.2.1 Client credentials flow | ✅ Built-in | Client Credentials | Complete |
| 2.3.2.2 Service account roles | ✅ Built-in | N/A | Complete |
| 2.3.2.3 API-to-API authentication | ✅ Built-in | Client Credentials | Complete |
| 2.3.2.4 Machine-to-machine | ✅ Built-in | Client Credentials | Complete |

**OAuth2 Flow:** Client Credentials
**Clients:** All confidential clients with service accounts enabled

---

## 3. OpenID Connect Flow Comparison

### 3.1 Flow Types Supported

| Flow Type | Client Type | Use Case | Enabled | Security | OTP/2FA | Spec Ref | Recommendation |
|-----------|-------------|----------|---------|----------|---------|----------|----------------|
| **Authorization Code + PKCE** | Public | Web/Mobile | ✅ Yes | ⭐⭐⭐⭐⭐ | ✅ Yes | REQ-AUTH-002 | **Primary** |
| **Authorization Code** | Confidential | Backend | ✅ Yes | ⭐⭐⭐⭐ | ✅ Yes | REQ-AUTH-002 | Good |
| **Resource Owner Password** | Confidential/Public | Legacy | ✅ Yes | ⭐⭐⭐ | ✅ Yes | N/A | **Migrate Away** |
| **Client Credentials** | Confidential | Service-to-Service | ✅ Yes | ⭐⭐⭐⭐ | ❌ No | REQ-ADMIN-002 | Good |
| **Implicit Flow** | Public | Legacy SPA | ❌ Disabled | ⭐ | ❌ No | N/A | **Deprecated** |
| **Token Exchange** | Confidential | Impersonation | ✅ Yes | ⭐⭐⭐⭐ | N/A | REQ-ADMIN-001 | Admin Only |

### 3.2 Flow Selection Decision Tree

```
User Authentication Needed?
├─ YES: Is it a browser-based app?
│   ├─ YES: Use Authorization Code + PKCE
│   │        → Keycloak Flow: browser
│   │        → Supports: Password, OTP, Social, 2FA
│   │        → Spec: REQ-AUTH-002, REQ-AUTH-003
│   │
│   └─ NO: Is it a mobile app?
│       ├─ YES: Use Authorization Code + PKCE
│       │        → Keycloak Flow: browser (via web view)
│       │        → Or direct grant (legacy, migrate away)
│       │
│       └─ NO: Is it a backend service?
│           └─ YES: Use Authorization Code (without PKCE)
│                    → Keycloak Flow: browser
│
└─ NO: Is it service-to-service communication?
    ├─ YES: Use Client Credentials
    │        → No Keycloak flow needed
    │        → Spec: REQ-ADMIN-002
    │
    └─ NO: Is it admin impersonation?
        └─ YES: Use Token Exchange
                 → No Keycloak flow needed
                 → Spec: REQ-ADMIN-001
```

### 3.3 Detailed Flow Recommendations

#### 3.3.1 Authorization Code + PKCE (Primary Recommendation)

**Use For:** (REQ-AUTH-002)
- Single Page Applications (React, Vue, Angular)
- Mobile applications (iOS, Android, React Native)
- Progressive Web Apps (PWA)
- Any public client

**Why:**
- Most secure option for public clients
- Prevents authorization code interception
- Full 2FA/OTP support (REQ-AUTH-003)
- No client secret needed

**Keycloak Flow:** `browser`

**OTP/2FA Support:** ✅ **YES**
- OTP verification happens automatically during login
- Transparent to client application
- No special client-side handling required

#### 3.3.2 Resource Owner Password Credentials (Use Sparingly)

**Use For:**
- ⚠️ Legacy systems during migration
- ⚠️ Trusted first-party mobile apps
- ⚠️ Admin tools and CLIs

**Why to Avoid:**
- Exposes user credentials to client
- Less secure than Authorization Code
- Should migrate to Auth Code + PKCE

**Keycloak Flow:** `direct grant`

**Migration Path:**
1. Current: Direct Grant (ROPC)
2. Intermediate: Add web view for Auth Code + PKCE
3. Target: Full Auth Code + PKCE implementation

#### 3.3.3 Client Credentials (Service Accounts)

**Use For:** (REQ-ADMIN-002)
- Backend microservices
- API-to-API communication
- Scheduled jobs
- Service accounts

**Why:**
- Appropriate for machine-to-machine
- No user context needed
- Secure with client secrets

**Keycloak Flow:** N/A (OAuth2 endpoint only)

---

## 4. Standard Authentication Flows

### 4.1 Browser Flow (Primary User Authentication)

**Flow Name:** `browser`
**Type:** Browser-based
**Bound To:** Browser authentication
**Spec Coverage:** REQ-AUTH-002, REQ-AUTH-003

#### 4.1.1 Flow Structure

```
browser (Top-Level Flow)
├─ auth-cookie (ALTERNATIVE)
│  └─ Checks for existing SSO session cookie
│
├─ auth-spnego (DISABLED)
│  └─ Kerberos/SPNEGO authentication (enterprise)
│
├─ identity-provider-redirector (ALTERNATIVE)
│  └─ Redirects to configured IdPs (Google, Microsoft)
│
└─ forms (ALTERNATIVE - Sub-Flow)
   ├─ auth-username-password-form (REQUIRED)
   │  └─ Username/Email + Password entry
   │
   └─ Browser - Conditional OTP (CONDITIONAL - Sub-Flow)
      ├─ conditional-user-configured (REQUIRED)
      │  └─ Checks if user has OTP configured
      │
      └─ auth-otp-form (REQUIRED)
         └─ Prompts for TOTP/OTP code if configured
```

#### 4.1.2 Specification Mapping

| Flow Component | Spec Requirement | Description |
|----------------|------------------|-------------|
| auth-username-password-form | REQ-AUTH-002.1 | Password-based login |
| identity-provider-redirector | REQ-AUTH-002.3 | Social login (Google, Microsoft) |
| Conditional OTP | REQ-AUTH-003 | Two-factor authentication |
| auth-cookie | REQ-TOKEN-002 | SSO session management |

#### 4.1.3 User Journey

1. **User visits login page**
   - Keycloak checks for SSO cookie
   - If valid → Logged in immediately (REQ-TOKEN-002)

2. **No SSO session**
   - User enters username/password (REQ-AUTH-002.1)
   - Or clicks social provider (REQ-AUTH-002.3)

3. **If 2FA/OTP configured** (REQ-AUTH-003)
   - User enters 6-digit TOTP code
   - Validated against user's OTP secret

4. **Success**
   - SSO session created
   - Authorization code generated
   - Client exchanges code for tokens

#### 4.1.4 Integration with OAuth2 Flows

```
Client Initiates Auth Code + PKCE
  ↓
Redirects to Keycloak /auth endpoint
  ↓
Browser Flow Executes
  ├─ Check SSO Cookie (REQ-TOKEN-002.1)
  ├─ Username/Password OR Social Login (REQ-AUTH-002)
  └─ OTP if configured (REQ-AUTH-003)
  ↓
Authorization Code Generated
  ↓
Redirect to Client with code
  ↓
Client exchanges code + PKCE verifier
  ↓
Access Token + Refresh Token Issued (REQ-TOKEN-001)
```

---

### 4.2 Registration Flow (User Signup)

**Flow Name:** `registration`
**Type:** Browser-based
**Bound To:** User registration
**Spec Coverage:** REQ-AUTH-001

#### 4.2.1 Flow Structure

```
registration (Top-Level Flow)
└─ registration form (REQUIRED - Sub-Flow)
   ├─ registration-user-creation (REQUIRED)
   │  └─ Creates new user account
   │
   ├─ registration-profile-action (REQUIRED)
   │  └─ Collects: firstName, lastName, email
   │
   ├─ registration-password-action (REQUIRED)
   │  └─ Sets user password
   │
   └─ registration-recaptcha-action (DISABLED)
      └─ reCAPTCHA verification (⚠️ Recommended to enable)
```

#### 4.2.2 Specification Mapping

| Flow Component | Spec Requirement | Description |
|----------------|------------------|-------------|
| registration-user-creation | REQ-AUTH-001.1 | Email/password registration |
| registration-profile-action | REQ-AUTH-001.4 | User profile creation |
| registration-password-action | REQ-AUTH-004.4 | Password policy enforcement |
| Email verification | REQ-AUTH-001.3 | ⚠️ DISABLED - Enable required |

#### 4.2.3 Current Issues & Recommendations

| Issue | Current State | Spec Requirement | Recommendation |
|-------|---------------|------------------|----------------|
| Email verification | ⚠️ DISABLED | REQ-AUTH-001.3 | **Enable immediately** |
| reCAPTCHA | ⚠️ DISABLED | REQ-SEC-003 | Enable for security |
| Social registration | ✅ Via IdP | REQ-AUTH-001.2 | Working correctly |

---

### 4.3 Direct Grant Flow (Resource Owner Password)

**Flow Name:** `direct grant`
**Type:** API-based
**Bound To:** Direct Access Grants
**Spec Coverage:** Legacy support, migrate to REQ-AUTH-002

#### 4.3.1 Flow Structure

```
direct grant (Top-Level Flow)
├─ direct-grant-validate-username (REQUIRED)
│  └─ Validates username/email exists
│
├─ direct-grant-validate-password (REQUIRED)
│  └─ Validates password matches
│
└─ Direct Grant - Conditional OTP (CONDITIONAL - Sub-Flow)
   ├─ conditional-user-configured (REQUIRED)
   │  └─ Checks if user has OTP configured
   │
   └─ direct-grant-validate-otp (REQUIRED)
      └─ Validates TOTP code from request parameter
```

#### 4.3.2 Usage Recommendation

⚠️ **Use Sparingly - Plan Migration**

**Current Use Cases:**
- Legacy mobile apps
- CLI tools
- Admin utilities

**Migration Strategy:**
1. Identify all direct grant usage
2. Plan migration to Auth Code + PKCE
3. Implement web view for mobile apps
4. Deprecate direct grant endpoints

#### 4.3.3 API Example

```bash
POST /realms/eworksuite/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=password&
client_id=eworksuite&
client_secret=YOUR_SECRET&
username=user@example.com&
password=userpassword&
totp=123456  # If 2FA enabled
```

---

### 4.4 Reset Credentials Flow (Password Reset)

**Flow Name:** `reset credentials`
**Type:** Browser-based
**Bound To:** Password reset
**Spec Coverage:** REQ-AUTH-004

#### 4.4.1 Flow Structure

```
reset credentials (Top-Level Flow)
├─ reset-credentials-choose-user (REQUIRED)
│  └─ User enters username/email
│
├─ reset-credential-email (REQUIRED)
│  └─ Sends password reset email
│
├─ reset-password (REQUIRED)
│  └─ User sets new password
│
└─ Reset - Conditional OTP (CONDITIONAL - Sub-Flow)
   ├─ conditional-user-configured (REQUIRED)
   │  └─ Checks if user has OTP configured
   │
   └─ reset-otp (REQUIRED)
      └─ Resets OTP configuration if needed
```

#### 4.4.2 Specification Mapping

| Flow Component | Spec Requirement | Description |
|----------------|------------------|-------------|
| reset-credential-email | REQ-AUTH-004.1 | Email-based password reset |
| reset-credentials-choose-user | REQ-AUTH-004.2 | Forgot password workflow |
| Token generation | REQ-AUTH-004.3 | Secure token with expiration (5 min) |
| reset-password | REQ-AUTH-004.4 | Password policy enforcement |

#### 4.4.3 Reset Journey

1. User clicks "Forgot Password"
2. Enters email/username (REQ-AUTH-004.2)
3. Reset email sent (REQ-AUTH-004.1)
4. Clicks link with secure token (REQ-AUTH-004.3)
5. Sets new password (REQ-AUTH-004.4)
6. Optional: Reset OTP if configured

---

### 4.5 First Broker Login Flow (Social Authentication)

**Flow Name:** `first broker login`
**Type:** Browser-based
**Bound To:** Social identity provider login
**Spec Coverage:** REQ-AUTH-002.3, REQ-AUTH-001.2

#### 4.5.1 Flow Structure

```
first broker login (Top-Level Flow)
├─ idp-review-profile (REQUIRED)
│  └─ Reviews profile from social provider
│
└─ User creation or linking (REQUIRED - Sub-Flow)
   ├─ idp-create-user-if-unique (ALTERNATIVE)
   │  └─ Creates new user if email not found (REQ-AUTH-001.2)
   │
   └─ Handle Existing Account (ALTERNATIVE - Sub-Flow)
      ├─ idp-confirm-link (REQUIRED)
      │  └─ Asks to link with existing account
      │
      └─ Account verification options (REQUIRED - Sub-Flow)
         ├─ idp-email-verification (ALTERNATIVE)
         │  └─ Send verification email
         │
         └─ Verify by Re-authentication
            ├─ idp-username-password-form (REQUIRED)
            │  └─ Enter existing password
            │
            └─ First broker login - Conditional OTP (CONDITIONAL)
               └─ Enter OTP if configured (REQ-AUTH-003)
```

#### 4.5.2 Configured Identity Providers

| Provider | Client ID | Spec Ref | Status |
|----------|-----------|----------|--------|
| Google OAuth 2.0 | 378565547237-* | REQ-AUTH-002.3 | ✅ Active |
| Microsoft (GitHub) | e728d87dafa329b0b367 | REQ-AUTH-002.3 | ✅ Active |
| GitLab OAuth 2.0 | abcc8c39db73fa6b* | REQ-AUTH-002.3 | ✅ Active |

#### 4.5.3 Social Login Scenarios

**Scenario A: New User (Email not found)**
1. User authenticates with Google
2. Profile retrieved from Google
3. New Keycloak account created automatically (REQ-AUTH-001.2)
4. Google account linked
5. User logged in

**Scenario B: Existing User (Email found)**
1. User authenticates with Google
2. Email matches existing account
3. User prompted to link accounts (REQ-UX-001)
4. Must verify: Email link OR existing password + OTP (REQ-AUTH-003)
5. Accounts linked
6. User logged in

---

## 5. Custom Authentication Flows

### 5.1 Direct Grant With OTP Instead of Password (Passwordless)

**Flow Name:** `Direct Grant With OTP instead of Password`
**Type:** Custom - Passwordless
**Used By:** `eworksuite_otp` client
**Spec Coverage:** REQ-AUTH-002.2 (OTP-based authentication)

#### 5.1.1 Purpose

Authenticate users with TOTP only, without password. Supports passwordless authentication use case.

#### 5.1.2 Flow Structure

```
Direct Grant With OTP instead of Password
├─ direct-grant-validate-username (REQUIRED)
│  └─ Validates username/email
│
├─ direct-grant-validate-password (DISABLED)
│  └─ ⚠️ Password validation SKIPPED
│
└─ Conditional OTP (CONDITIONAL - Sub-Flow)
   ├─ conditional-user-configured (REQUIRED)
   │  └─ User MUST have OTP configured
   │
   └─ direct-grant-validate-otp (REQUIRED)
      └─ TOTP code REQUIRED for authentication
```

#### 5.1.3 API Usage

```bash
POST /realms/eworksuite/protocol/openid-connect/token

grant_type=password&
client_id=eworksuite_otp&
client_secret=YOUR_SECRET&
username=user@example.com&
totp=123456
# Note: NO password parameter
```

#### 5.1.4 Use Case

Mobile app with device-based TOTP:
1. User registers, TOTP secret stored
2. App generates current TOTP code
3. App authenticates with username + TOTP only
4. No password needed (REQ-AUTH-002.2)

---

### 5.2 Copy of Direct Grant (Enhanced Error Handling)

**Flow Name:** `Copy of direct grant`
**Type:** Custom - Script-based validation
**Used By:** `eworksuite_public_impersonate`

#### 5.2.1 Purpose

Enhanced OTP validation with custom OAuth2-compliant error messages.

#### 5.2.2 Custom Script Logic

```javascript
// Validates OTP parameter is present
// Returns proper OAuth 2.0 error response

if(null === context.getHttpRequest()
           .getDecodedFormParameters()
           .getFirst("totp")){

    context.failure(
        AuthenticationFlowError.INVALID_CREDENTIALS,
        Response.status(ResponseStatus.UNAUTHORIZED)
            .entity('{"error":"invalid_grant",
                     "error_description":"OTP missing"}')
            .type("application/json")
            .build()
    );
    return;
}
context.success();
```

#### 5.2.3 Error Responses

**Without OTP:**
```json
{
  "error": "invalid_grant",
  "error_description": "OTP missing"
}
```

**Standard Keycloak Error:**
```json
{
  "error": "invalid_grant",
  "error_description": "Invalid user credentials"
}
```

---

### 5.3 WebAuthn Flow (Biometric Authentication)

**Flow Name:** `WebAuthn`
**Type:** Custom - Passwordless biometric
**Spec Coverage:** Partial support for REQ-SEC-001 (WebAuthn/FIDO2)

#### 5.3.1 Purpose

Support WebAuthn/FIDO2 authentication:
- Fingerprint (Touch ID, Android Biometric)
- Face ID
- Hardware security keys (YubiKey)
- Platform authenticators (Windows Hello)

#### 5.3.2 Current Limitations

⚠️ **Partial Implementation**

| Feature | Status | Spec Ref | Action Needed |
|---------|--------|----------|---------------|
| Platform authenticators | ✅ Partial | REQ-SEC-001.3 | Enhance |
| Hardware keys | ✅ Partial | REQ-SEC-001.2 | Enhance |
| Passwordless | ✅ Partial | REQ-SEC-001.1 | Enhance |
| Multi-device sync | ❌ Missing | REQ-SEC-001.4 | Implement |

#### 5.3.3 Enhancement Roadmap

Align with specification REQ-SEC-001:

**Phase 1 (Q2 2026):**
- Full passwordless authentication
- Platform authenticator support
- Hardware key support

**Phase 2 (Q3 2026):**
- Multi-device credential sync
- Passkey management UI
- Recovery flows

---

## 6. Flow Selection Guide

### 6.1 Quick Reference by Use Case

| Use Case | Spec Ref | OAuth2 Flow | Keycloak Flow | Client Type |
|----------|----------|-------------|---------------|-------------|
| **User Registration** | REQ-AUTH-001 | N/A | `registration` | N/A |
| **Web App Login** | REQ-AUTH-002 | Auth Code + PKCE | `browser` | Public |
| **Mobile App Login** | REQ-AUTH-002 | Auth Code + PKCE | `browser` | Public |
| **Social Login** | REQ-AUTH-002.3 | Auth Code + PKCE | `browser` + IdP | Public |
| **Passwordless (OTP)** | REQ-AUTH-002.2 | ROPC (custom) | `Direct Grant With OTP` | Confidential |
| **2FA/OTP** | REQ-AUTH-003 | N/A (automatic) | Conditional OTP | N/A |
| **Password Reset** | REQ-AUTH-004 | N/A | `reset credentials` | N/A |
| **Token Refresh** | REQ-TOKEN-001 | Refresh Token | N/A | All |
| **SSO** | REQ-TOKEN-002 | Auth Code + PKCE | `browser` | Public |
| **Admin Impersonation** | REQ-ADMIN-001 | Token Exchange | N/A | Confidential |
| **Service Account** | REQ-ADMIN-002 | Client Credentials | N/A | Confidential |
| **Legacy Mobile** | N/A | ROPC | `direct grant` | Confidential |

### 6.2 Client Configuration Examples

#### 6.2.1 Public Web/Mobile App (Recommended)

```yaml
Client ID: eworksuite_public
Client Type: Public
Standard Flow: Enabled (Auth Code + PKCE)
Direct Access Grants: Disabled
PKCE: Required (S256)

Flows Used:
  - Browser flow (password, social, OTP)
  - Registration flow
  - Reset credentials flow

Spec Coverage:
  - REQ-AUTH-001 (Registration)
  - REQ-AUTH-002 (Login)
  - REQ-AUTH-003 (2FA)
  - REQ-AUTH-004 (Password reset)
  - REQ-TOKEN-001 (Token refresh)
  - REQ-TOKEN-002 (SSO)
```

#### 6.2.2 Confidential Backend Service

```yaml
Client ID: eworksuite_service
Client Type: Confidential
Client Secret: *****
Service Accounts: Enabled
Client Credentials: Enabled

Flows Used:
  - None (OAuth2 only)

Spec Coverage:
  - REQ-ADMIN-002 (Service account)
```

#### 6.2.3 Admin Impersonation Client

```yaml
Client ID: eworksuite_business
Client Type: Confidential
Client Secret: *****
Token Exchange: Enabled
Permissions: impersonate, token-exchange

Flows Used:
  - None (OAuth2 only)

Spec Coverage:
  - REQ-ADMIN-001 (Impersonation)
```

---

## 7. Implementation Examples

### 7.1 Authorization Code + PKCE (Web/Mobile)

#### 7.1.1 JavaScript (Web) Example

```javascript
// Step 1: Generate PKCE challenge
async function generatePKCE() {
  const verifier = generateRandomString(128);
  const challenge = await sha256(verifier);
  return { verifier, challenge };
}

// Step 2: Initiate login
const { verifier, challenge } = await generatePKCE();
const authUrl = `https://keycloak.example.com/realms/eworksuite/protocol/openid-connect/auth?` +
  `client_id=eworksuite_public&` +
  `redirect_uri=${encodeURIComponent(window.location.origin + '/callback')}&` +
  `response_type=code&` +
  `scope=openid profile email&` +
  `code_challenge=${challenge}&` +
  `code_challenge_method=S256`;

window.location.href = authUrl;

// Step 3: Handle callback
const code = new URLSearchParams(window.location.search).get('code');
const tokenResponse = await fetch('/realms/eworksuite/protocol/openid-connect/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: 'eworksuite_public',
    code: code,
    redirect_uri: window.location.origin + '/callback',
    code_verifier: verifier // PKCE verifier
  })
});

const tokens = await tokenResponse.json();
// tokens.access_token, tokens.refresh_token
```

**Spec Coverage:** REQ-AUTH-002 (Login), REQ-TOKEN-001 (Token refresh)

#### 7.1.2 React Native Example

```javascript
import { authorize } from 'react-native-app-auth';

const config = {
  issuer: 'https://keycloak.example.com/realms/eworksuite',
  clientId: 'eworksuite_public',
  redirectUrl: 'com.eworksuite.app://callback',
  scopes: ['openid', 'profile', 'email', 'offline_access'],
  usePKCE: true, // Enable PKCE
};

// Initiate login
const result = await authorize(config);
// result.accessToken, result.refreshToken

// Refresh token
const refreshResult = await refresh(config, {
  refreshToken: result.refreshToken
});
```

**Spec Coverage:** REQ-AUTH-002, REQ-AUTH-003 (2FA works automatically)

### 7.2 Token Refresh (All Clients)

#### 7.2.1 Automatic Refresh Example

```javascript
// REQ-TOKEN-001: Automatic token refresh

let accessToken = tokens.access_token;
let refreshToken = tokens.refresh_token;

async function getValidToken() {
  // Check if token expired
  const decoded = jwtDecode(accessToken);
  const now = Date.now() / 1000;

  if (decoded.exp < now + 60) { // Refresh 1 min before expiry
    const response = await fetch('/realms/eworksuite/protocol/openid-connect/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: 'eworksuite_public',
        refresh_token: refreshToken
      })
    });

    const newTokens = await response.json();
    accessToken = newTokens.access_token;
    refreshToken = newTokens.refresh_token; // Rotation

    // Store new tokens
    localStorage.setItem('tokens', JSON.stringify(newTokens));
  }

  return accessToken;
}

// Use in API calls
const token = await getValidToken();
fetch('/api/data', {
  headers: { Authorization: `Bearer ${token}` }
});
```

**Spec Coverage:** REQ-TOKEN-001.1, REQ-TOKEN-001.2 (Rotation), REQ-TOKEN-001.3 (Single-use)

### 7.3 Admin Impersonation (Token Exchange)

#### 7.3.1 Python FastAPI Example

```python
# REQ-ADMIN-001: Admin impersonation

import httpx
from fastapi import HTTPException

async def impersonate_user(admin_token: str, user_id: str) -> dict:
    """
    Admin impersonates user via token exchange.
    Spec: REQ-ADMIN-001.1
    """
    token_url = "https://keycloak.example.com/realms/eworksuite/protocol/openid-connect/token"

    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": "eworksuite_business",
        "client_secret": "YOUR_SECRET",
        "subject_token": admin_token,
        "requested_subject": user_id,
        "audience": "eworksuite",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)

        if response.status_code != 200:
            raise HTTPException(status_code=403, detail="Impersonation not allowed")

        # Returns impersonated user's token
        # Audit trail automatically logged (REQ-ADMIN-001.2)
        return response.json()

# Usage
@app.post("/admin/impersonate/{user_id}")
async def impersonate(user_id: str, admin_token: str = Depends(get_admin_token)):
    tokens = await impersonate_user(admin_token, user_id)
    # tokens['access_token'] now represents the target user
    return {"impersonated_token": tokens['access_token']}
```

**Spec Coverage:** REQ-ADMIN-001 (Full impersonation flow with audit)

### 7.4 Service Account Authentication

#### 7.4.1 Python Example

```python
# REQ-ADMIN-002: Service account authentication

import httpx

async def get_service_token() -> str:
    """
    Get service account token for API-to-API calls.
    Spec: REQ-ADMIN-002.1, REQ-ADMIN-002.3
    """
    token_url = "https://keycloak.example.com/realms/eworksuite/protocol/openid-connect/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": "eworksuite_service",
        "client_secret": "YOUR_SECRET",
        "scope": "openid"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        tokens = response.json()
        return tokens['access_token']

# Usage in microservice
async def call_protected_api():
    token = await get_service_token()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.example.com/internal/data",
            headers={"Authorization": f"Bearer {token}"}
        )
        return response.json()
```

**Spec Coverage:** REQ-ADMIN-002 (Machine-to-machine auth)

---

## 8. Security Recommendations

### 8.1 Critical Security Issues (From Specification)

#### 8.1.1 Enable Email Verification (REQ-AUTH-001.3)

**Current Status:** ⚠️ DISABLED
**Risk:** Users can register with fake emails
**Spec Ref:** REQ-AUTH-001.3
**Priority:** CRITICAL

**Action:**
```
Realm Settings → Login → Verify email: ON
Required Actions → VERIFY_EMAIL: Enabled, Default Action
```

#### 8.1.2 Enable Brute Force Protection (REQ-SEC-003)

**Current Status:** ⚠️ DISABLED
**Risk:** Vulnerable to password guessing attacks
**Spec Ref:** REQ-SEC-003
**Priority:** CRITICAL

**Action:**
```
Realm Settings → Security Defenses → Brute Force Detection: ON
Configuration:
  - Max Login Failures: 5
  - Wait Increment: 60 seconds
  - Max Wait: 900 seconds (15 min)
  - Failure Reset Time: 12 hours
```

#### 8.1.3 Reduce Access Token Lifetime

**Current Status:** ⚠️ 12 hours
**Risk:** Extended window for token theft
**Spec Ref:** Phase 1 Roadmap
**Priority:** CRITICAL

**Action:**
```
Realm Settings → Tokens → Access Token Lifespan: 15-30 minutes
```

### 8.2 Flow-Specific Security

#### 8.2.1 Browser Flow Security

- ✅ PKCE required for public clients
- ✅ HTTPOnly cookies for SSO
- ✅ CSRF protection enabled
- ⚠️ Enable brute force protection
- ⚠️ Add reCAPTCHA to registration

#### 8.2.2 Direct Grant Security

- ⚠️ Use only for legacy migration
- ✅ Always use HTTPS
- ✅ Implement rate limiting
- ✅ Short-lived access tokens
- 📋 Plan migration to Auth Code + PKCE

#### 8.2.3 Token Exchange Security

- ✅ Limited to admin clients only
- ✅ Authorization policies enforced
- ✅ Audit trail enabled
- ✅ Time-limited impersonation

### 8.3 Specification Alignment Checklist

| Security Requirement | Spec Ref | Status | Action |
|---------------------|----------|--------|--------|
| Email verification | REQ-AUTH-001.3 | ❌ DISABLED | Enable now |
| Brute force protection | REQ-SEC-003 | ❌ DISABLED | Enable now |
| Rate limiting | REQ-ENT-004 | ❌ Missing | Implement (Phase 1) |
| Token lifetime (15-30min) | Phase 1 | ❌ 12 hours | Reduce now |
| Password policy (strong) | REQ-AUTH-004.4 | ⚠️ Weak | Enhance |
| Audit logging | REQ-AUDIT-001 | ⚠️ Basic | Enhance (Phase 1) |
| reCAPTCHA | REQ-SEC-003.3 | ❌ DISABLED | Enable |

---

## Appendix A: Flow Decision Matrix

### Quick Reference Table

| Scenario | OAuth2 Flow | Keycloak Flow | Spec Ref | Priority |
|----------|-------------|---------------|----------|----------|
| Web app user login | Auth Code + PKCE | browser | REQ-AUTH-002 | ✅ Primary |
| Mobile app user login | Auth Code + PKCE | browser | REQ-AUTH-002 | ✅ Primary |
| Social login (any) | Auth Code + PKCE | browser + IdP | REQ-AUTH-002.3 | ✅ Primary |
| User registration | N/A | registration | REQ-AUTH-001 | ✅ Primary |
| Password reset | N/A | reset credentials | REQ-AUTH-004 | ✅ Primary |
| 2FA/OTP | Automatic | Conditional OTP | REQ-AUTH-003 | ✅ Primary |
| SSO across apps | Auth Code + PKCE | browser | REQ-TOKEN-002 | ✅ Primary |
| Token refresh | Refresh Token | N/A | REQ-TOKEN-001 | ✅ Primary |
| Service-to-service | Client Credentials | N/A | REQ-ADMIN-002 | ✅ Primary |
| Admin impersonation | Token Exchange | N/A | REQ-ADMIN-001 | ✅ Primary |
| Passwordless (OTP) | ROPC (custom) | Direct Grant With OTP | REQ-AUTH-002.2 | ✅ Active |
| Legacy mobile app | ROPC | direct grant | N/A | ⚠️ Migrate |
| CLI/Admin tools | ROPC | direct grant | N/A | ⚠️ Migrate |

---

## Appendix B: Glossary

**Auth Code + PKCE:** Authorization Code flow with Proof Key for Code Exchange
**ROPC:** Resource Owner Password Credentials (Direct Grant)
**SSO:** Single Sign-On
**TOTP:** Time-based One-Time Password
**2FA:** Two-Factor Authentication
**IdP:** Identity Provider

---

**Document End**
