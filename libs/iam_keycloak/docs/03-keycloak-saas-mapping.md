# Keycloak SaaS Mapping - Multi-Tenancy Implementation

**Document Version:** 1.0
**Last Updated:** November 29, 2025
**Status:** Production
**Related Specification:**
- [eWorkSuite IAM Service Specification](01-eworksuite-iam-service.md)
- [Keycloak Authentication Flows](02-keycloak-auth-flows.md)
- [Keycloak Organizations Announcement](https://www.keycloak.org/2024/06/announcement-keycloak-organizations)
- [Managing Organizations Documentation](https://www.keycloak.org/docs/latest/server_admin/#_managing_organizations)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Multi-Tenancy Architecture](#2-multi-tenancy-architecture)
3. [Keycloak Organizations Feature](#3-keycloak-organizations-feature)
4. [Feature Mapping to Specification](#4-feature-mapping-to-specification)
5. [Implementation Approaches](#5-implementation-approaches)
6. [Migration Path](#6-migration-path)
7. [Alternative Solutions](#7-alternative-solutions)

---

## 1. Overview

### 1.1 Document Purpose

This document maps Keycloak features to the [eWorkSuite IAM Service](01-eworksuite-iam-service.md) specification, focusing on **multi-tenancy (REQ-ENT-002)** and SaaS B2B/B2B2C use cases.

**Key Goal:** Design a flexible IAM architecture that can wrap:
- ✅ Keycloak (current)
- 🔄 AWS Cognito (future)
- 🔄 Auth0 (future)
- 🔄 Azure AD B2C (future)

### 1.2 Scope

This document addresses:
- **Multi-tenancy isolation** for B2B SaaS customers
- **Organization management** for business partners
- **Identity federation** across tenant boundaries
- **Flexible authentication** based on tenant configuration
- **Token enrichment** with tenant/organization context

### 1.3 Key Requirements from Specification

From [eWorkSuite IAM Specification](01-eworksuite-iam-service.md), Section 3.5.2:

**REQ-ENT-002: Multi-Tenancy Support (Priority: HIGH)**
- **3.5.2.1** Isolated tenant realms/namespaces
- **3.5.2.2** Tenant-specific branding and themes
- **3.5.2.3** Tenant-level admin roles
- **3.5.2.4** Tenant usage analytics and quotas
- **3.5.2.5** Cross-tenant user lookup prevention

---

## 2. Multi-Tenancy Architecture

### 2.1 Multi-Tenancy Models

There are three common approaches for implementing multi-tenancy in IAM:

```
┌─────────────────────────────────────────────────────────────────┐
│ Model            │ Isolation │ Complexity │ Scalability │ Cost  │
├──────────────────┼───────────┼────────────┼─────────────┼───────┤
│ 1. Realm per     │ ★★★★★     │ ★★★☆☆      │ ★★★☆☆       │ ★★★★★ │
│    Tenant        │ Complete  │ Medium     │ Good        │ High  │
├──────────────────┼───────────┼────────────┼─────────────┼───────┤
│ 2. Shared Realm  │ ★★★☆☆     │ ★★★★☆      │ ★★★★★       │ ★★☆☆☆ │
│    + Groups      │ Logical   │ High       │ Excellent   │ Low   │
├──────────────────┼───────────┼────────────┼─────────────┼───────┤
│ 3. Organizations │ ★★★★☆     │ ★★☆☆☆      │ ★★★★☆       │ ★★★☆☆ │
│    Feature       │ Strong    │ Low        │ Very Good   │ Medium│
│    (Keycloak 25+)│           │            │             │       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Model Comparison

#### 2.2.1 Realm per Tenant (Complete Isolation)

**Architecture:**
```
eWorkSuite Master Realm
├── Tenant A Realm
│   ├── Users (tenant-a-*)
│   ├── Roles (tenant-specific)
│   ├── Clients (tenant-specific)
│   └── Identity Providers (tenant-specific)
│
├── Tenant B Realm
│   ├── Users (tenant-b-*)
│   ├── Roles (tenant-specific)
│   └── ...
│
└── Tenant C Realm
    └── ...
```

**Pros:**
- ✅ Complete isolation (REQ-ENT-002.1)
- ✅ Independent branding/themes (REQ-ENT-002.2)
- ✅ Separate admin roles (REQ-ENT-002.3)
- ✅ Easy quotas/analytics (REQ-ENT-002.4)
- ✅ No cross-tenant leakage (REQ-ENT-002.5)

**Cons:**
- ❌ High resource overhead
- ❌ Difficult to manage many tenants
- ❌ Complex SSO across tenants
- ❌ Harder to share identity providers
- ❌ Database growth issues at scale

**Use Cases:** Small number of large enterprise tenants (5-50)

#### 2.2.2 Shared Realm + Groups (Logical Isolation)

**Architecture:**
```
eWorkSuite Shared Realm
├── Group: TenantA
│   ├── Users (with tenantId attribute)
│   ├── Subgroups (roles)
│   └── Attributes (tenant config)
│
├── Group: TenantB
│   ├── Users (with tenantId attribute)
│   └── ...
│
└── Custom Code
    ├── Authorization filters
    ├── Token enrichment
    └── Cross-tenant checks
```

**Pros:**
- ✅ Scales to thousands of tenants
- ✅ Lower resource usage
- ✅ Easier management
- ✅ Shared identity providers

**Cons:**
- ❌ Requires custom code for isolation
- ❌ Risk of cross-tenant leakage
- ❌ Complex authorization logic
- ❌ Limited branding flexibility
- ❌ Harder to audit per tenant

**Use Cases:** Large number of small/medium tenants (100s-1000s)

#### 2.2.3 Keycloak Organizations (Hybrid Approach)

**Architecture:**
```
eWorkSuite Realm (Organization-enabled)
├── Organization: CompanyA
│   ├── Members (managed/unmanaged)
│   ├── Domains (companya.com)
│   ├── Identity Providers (linked)
│   └── Attributes (org metadata)
│
├── Organization: CompanyB
│   ├── Members
│   ├── Domains (companyb.com)
│   └── ...
│
└── Realm Users (shared pool)
    ├── Can belong to 0-N organizations
    └── Organization context in tokens
```

**Pros:**
- ✅ Built-in isolation (no custom code)
- ✅ Identity-first login
- ✅ Automatic domain routing
- ✅ Organization metadata in tokens
- ✅ Flexible member management
- ✅ Good scalability (100s of orgs)

**Cons:**
- ⚠️ Technology Preview (Keycloak 25+)
- ❌ Limited branding customization
- ❌ No per-org admin roles yet
- ❌ Weaker isolation than realms
- ❌ Cannot enforce complete segregation

**Use Cases:** B2B SaaS with partner organizations (10-500)

---

## 3. Keycloak Organizations Feature

### 3.1 Overview

**Status:** Technology Preview (Keycloak 25+)
**Target:** Supported in Keycloak 26

The Organizations feature enables **Customer Identity and Access Management (CIAM)** for B2B and B2B2C scenarios by adding organization-level isolation within a single realm.

### 3.2 Core Capabilities

```yaml
Organizations Feature:
  ✅ Currently Available (Keycloak 25):
    - Create and manage organizations
    - Manage organization members
    - Link identity providers to organizations
    - Domain-based organization routing
    - Identity-first login flow
    - Organization claims in tokens
    - Member invitation links
    - Managed vs unmanaged members

  🔄 Roadmap (Keycloak 26+):
    - Per-organization admin roles
    - Organization-specific branding
    - Cross-organization SSO
    - Organization analytics dashboard
    - Advanced member provisioning
```

### 3.3 Key Concepts

#### 3.3.1 Organization Structure

```json
{
  "name": "Acme Corporation",
  "alias": "acme-corp",
  "domains": ["acme.com", "acmecorp.com"],
  "enabled": true,
  "attributes": {
    "industry": "manufacturing",
    "tier": "enterprise",
    "maxUsers": "500"
  },
  "redirectUrl": "https://portal.acme.com",
  "description": "Main partner organization"
}
```

#### 3.3.2 Organization Members

**Two Types:**

1. **Managed Members**
   - Federated from organization's IdP
   - Lifecycle managed by organization
   - Deleted when organization is deleted
   - Email domain must match organization domain

2. **Unmanaged Members**
   - Existing realm users
   - Added manually to organization
   - Remain in realm if organization is deleted
   - Can have any email domain

#### 3.3.3 Domain Routing

**Automatic Organization Detection:**

```
User Input: alice@acme.com
    ↓
Domain Match: acme.com → Acme Corp Organization
    ↓
Authentication Flow:
  - If org has IdP with domain → Redirect to IdP
  - If org has public IdP → Show IdP option
  - Else → Username/password flow
    ↓
Token Claims:
{
  "organization": {
    "acme-corp": {
      "id": "org-uuid-123",
      "name": "Acme Corporation"
    }
  }
}
```

### 3.4 Identity-First Login Flow

**Standard Flow (No Organizations):**
```
┌──────────────────────────┐
│ Username + Password Form │
└──────────────────────────┘
```

**Identity-First Flow (With Organizations):**
```
Step 1:
┌──────────────────────────┐
│ Enter Email/Username     │
└──────────────────────────┘
        ↓
   Domain Match?
        ↓
    ┌───────┐
    │  Yes  │──→ Redirect to Org IdP (if configured)
    └───────┘     OR
        ↓          Show password prompt
    ┌───────┐
    │   No  │──→ Standard username/password
    └───────┘
```

**Authentication Flow Structure:**
```
browser (modified for organizations)
├─ cookie
├─ kerberos
├─ identity-provider-redirector
├─ forms
│  ├─ auth-username-form (identity-first)
│  ├─ auth-password-form
│  └─ conditional-otp
└─ organization-conditional
   ├─ condition-user-configured
   └─ organization-identity-first-login
```

### 3.5 Token Enrichment

**Organization Scope Request:**

```javascript
// Request organization scope
const authUrl = `${keycloakUrl}/realms/eworksuite/protocol/openid-connect/auth?` +
  `client_id=my-app&` +
  `scope=openid profile email organization&` +  // ← organization scope
  `response_type=code&` +
  `redirect_uri=${redirectUri}`;
```

**Token Claims:**

```json
{
  "sub": "user-uuid",
  "email": "alice@acme.com",
  "organization": {
    "acme-corp": {
      "id": "42c3e46f-2477-44d7-a85b-d3b43f6b31fa",
      "name": "Acme Corporation",
      "custom_attr": ["value1"]
    }
  }
}
```

**Scope Variants:**
- `organization` - Single org (prompts if multiple)
- `organization:acme-corp` - Specific organization by alias
- `organization:*` - All organizations user belongs to

---

## 4. Feature Mapping to Specification

### 4.1 REQ-ENT-002: Multi-Tenancy Support

```
┌────────────────────────────────────────────────────────────────────┐
│ Specification          │ Keycloak Orgs   │ Realm-per-Tenant       │
│ Requirement            │ Approach        │ Approach               │
├────────────────────────┼─────────────────┼────────────────────────┤
│ 3.5.2.1 Isolated       │ ⚠️ Partial      │ ✅ Complete            │
│ tenant realms          │ Logical in      │ Physical realms        │
│                        │ shared realm    │                        │
├────────────────────────┼─────────────────┼────────────────────────┤
│ 3.5.2.2 Tenant-        │ ❌ Not Yet      │ ✅ Full Support        │
│ specific branding      │ (Roadmap KC 26) │ Realm themes           │
├────────────────────────┼─────────────────┼────────────────────────┤
│ 3.5.2.3 Tenant-level   │ ❌ Not Yet      │ ✅ Realm Admin         │
│ admin roles            │ (Roadmap KC 26) │ Roles                  │
├────────────────────────┼─────────────────┼────────────────────────┤
│ 3.5.2.4 Tenant usage   │ ⚠️ Partial      │ ✅ Realm Events        │
│ analytics/quotas       │ Custom impl     │ Per-realm metrics      │
├────────────────────────┼─────────────────┼────────────────────────┤
│ 3.5.2.5 Cross-tenant   │ ✅ Enforced     │ ✅ Complete            │
│ user lookup            │ by domains      │ Physical separation    │
│ prevention             │                 │                        │
└────────────────────────────────────────────────────────────────────┘
```

### 4.2 Additional Requirements Mapping

#### 4.2.1 Authentication (Section 2.1)

| Spec Ref | Requirement | Organizations | Realm-per-Tenant |
|----------|-------------|---------------|------------------|
| REQ-AUTH-001 | User Registration | ✅ Supported | ✅ Supported |
| REQ-AUTH-002 | User Login | ✅ Identity-First | ✅ Standard |
| REQ-AUTH-003 | 2FA/OTP | ✅ Supported | ✅ Supported |
| REQ-AUTH-004 | Password Management | ✅ Supported | ✅ Supported |

#### 4.2.2 Token & Session (Section 2.2)

| Spec Ref | Requirement | Organizations | Realm-per-Tenant |
|----------|-------------|---------------|------------------|
| REQ-TOKEN-001 | Token Refresh | ✅ Supported | ✅ Supported |
| REQ-TOKEN-002 | SSO | ✅ Realm-level | ✅ Realm-level |

**Note:** Organizations adds `organization` claim to tokens for multi-tenant authorization.

#### 4.2.3 Admin Features (Section 2.3)

| Spec Ref | Requirement | Organizations | Realm-per-Tenant |
|----------|-------------|---------------|------------------|
| REQ-ADMIN-001 | Admin Impersonation | ✅ Supported | ✅ Supported |
| REQ-ADMIN-002 | Service Account | ✅ Supported | ✅ Supported |

---

## 5. Implementation Approaches

### 5.1 Recommended Approach: Keycloak Organizations

**Target Use Case:** eWorkSuite SaaS with 10-500 partner organizations

**Rationale:**
1. ✅ **Built-in support** - No custom isolation code needed
2. ✅ **Identity-first login** - Better UX for B2B scenarios
3. ✅ **Domain routing** - Automatic org detection
4. ✅ **Token enrichment** - Organization context built-in
5. ✅ **Scalability** - Handles 100s of organizations
6. ⚠️ **Roadmap alignment** - Missing features (branding, admin roles) planned for KC 26

**Implementation Steps:**

#### 5.1.1 Phase 1: Enable Organizations Feature

```bash
# Start Keycloak with organizations feature
docker run -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  -p 8080:8080 \
  quay.io/keycloak/keycloak:26.0 \
  start-dev --features=organization
```

#### 5.1.2 Phase 2: Realm Configuration

```yaml
# Enable Organizations in Realm Settings
Realm: eworksuite
  Settings:
    Organizations: ON

  Authentication Flows (auto-updated):
    - browser: Modified for identity-first login
    - first broker login: Auto-add to organization
```

#### 5.1.3 Phase 3: Create Organization Structure

```javascript
// Create organization via Admin API
POST /admin/realms/eworksuite/organizations
{
  "name": "Acme Corporation",
  "alias": "acme-corp",
  "domains": ["acme.com"],
  "enabled": true,
  "attributes": {
    "tenantId": "tenant-001",
    "tier": "enterprise",
    "maxUsers": "500"
  },
  "redirectUrl": "https://app.eworksuite.com/tenant/acme"
}
```

#### 5.1.4 Phase 4: Link Identity Provider

```javascript
// Link IdP to organization
POST /admin/realms/eworksuite/organizations/{orgId}/identity-providers
{
  "identityProvider": "acme-okta",
  "domain": "acme.com",
  "hideOnLoginPage": true
}
```

#### 5.1.5 Phase 5: Token Configuration

```javascript
// Client configuration
{
  "clientId": "eworksuite-web",
  "defaultClientScopes": [
    "openid",
    "profile",
    "email",
    "organization"  // ← Enable organization claims
  ]
}
```

#### 5.1.6 Phase 6: Application Integration

**Frontend (Next.js/React):**
```typescript
// Extract organization from token
import { useAuth } from '@/lib/auth';

export function useOrganization() {
  const { user } = useAuth();

  // Organization claim structure:
  // user.organization = {
  //   "acme-corp": { id: "...", name: "..." }
  // }

  const orgAlias = Object.keys(user?.organization || {})[0];
  const orgData = user?.organization?.[orgAlias];

  return {
    alias: orgAlias,
    id: orgData?.id,
    name: orgData?.name,
    isOrgUser: !!orgAlias
  };
}
```

**Backend (FastAPI):**
```python
from fastapi import Depends, HTTPException
from typing import Optional

def get_organization_context(token: dict = Depends(get_current_token)) -> Optional[dict]:
    """Extract organization context from JWT token"""
    org_claim = token.get("organization", {})

    if not org_claim:
        return None

    # Get first organization (user can only auth to one org at a time)
    org_alias = list(org_claim.keys())[0]
    org_data = org_claim[org_alias]

    return {
        "alias": org_alias,
        "id": org_data.get("id"),
        "attributes": org_data
    }

@app.get("/api/data")
async def get_data(org: dict = Depends(get_organization_context)):
    """Endpoint that requires organization context"""
    if not org:
        raise HTTPException(status_code=403, detail="Organization context required")

    # Filter data by organization
    return fetch_data_for_org(org["id"])
```

### 5.2 Alternative Approach: Realm per Tenant

**Target Use Case:** Small number of large enterprise customers (5-50)

**When to Use:**
- ✅ Complete isolation is regulatory requirement
- ✅ Each tenant needs independent configuration
- ✅ Tenants are large enterprises (1000s of users each)
- ✅ Custom per-tenant authentication flows
- ❌ NOT suitable for 100s-1000s of small tenants

**Implementation:**

```yaml
Master Realm:
  - Admin users only
  - Manages all tenant realms

Tenant Realm Pattern:
  Name: tenant-{customerId}
  Users: Prefix with tenant ID
  Roles: Tenant-specific
  Clients: Shared + tenant-specific
  Themes: Per-tenant branding
```

**Tenant Provisioning Flow:**
```python
# Pseudo-code for tenant provisioning
async def create_tenant(tenant_data: TenantCreate):
    # 1. Create Keycloak realm
    realm_name = f"tenant-{tenant_data.id}"
    await keycloak_admin.create_realm({
        "realm": realm_name,
        "enabled": True,
        "displayName": tenant_data.name
    })

    # 2. Configure realm
    await keycloak_admin.update_realm(realm_name, {
        "loginTheme": tenant_data.theme,
        "emailTheme": tenant_data.theme,
        "accessTokenLifespan": 900  # 15 min
    })

    # 3. Create tenant admin role
    await keycloak_admin.create_role(realm_name, {
        "name": "tenant-admin",
        "description": f"Admin for {tenant_data.name}"
    })

    # 4. Setup identity providers
    for idp in tenant_data.identity_providers:
        await keycloak_admin.create_identity_provider(realm_name, idp)

    # 5. Create clients
    await keycloak_admin.create_client(realm_name, {
        "clientId": "web-app",
        "rootUrl": f"https://{tenant_data.subdomain}.eworksuite.com"
    })

    return realm_name
```

### 5.3 Hybrid Approach

**Use Case:** Mix of organization types

```
eWorkSuite IAM Architecture
│
├── Master Realm (Admin only)
│
├── Shared Realm (Small/Medium Orgs)
│   ├── Organization: CompanyA (50 users)
│   ├── Organization: CompanyB (120 users)
│   └── Organization: CompanyC (80 users)
│
├── Enterprise Tenant 1 Realm (5000 users)
│   └── Complex custom flows
│
└── Enterprise Tenant 2 Realm (3000 users)
    └── SAML federation
```

**Decision Matrix:**

```
Tenant Size    │ Users │ Approach           │ Reason
───────────────┼───────┼────────────────────┼──────────────────────
Small          │ <100  │ Organizations      │ Cost-effective
Medium         │100-500│ Organizations      │ Good isolation
Large          │500-2K │ Organizations*     │ *Monitor performance
Enterprise     │ 2K+   │ Dedicated Realm    │ Complete isolation
```

---

## 6. Migration Path

### 6.1 Current State Assessment

**eWorkSuite Current Implementation:**
- Single realm: `eworksuite`
- All users in shared pool
- No tenant isolation
- Group-based permissions

### 6.2 Migration to Organizations

#### Phase 1: Preparation (Week 1-2)

**Tasks:**
1. ✅ Enable Organizations feature in dev/staging
2. ✅ Update authentication flows (auto-configured)
3. ✅ Add `organization` scope to clients
4. ✅ Test identity-first login
5. ✅ Update token parsing in applications

**Validation:**
```bash
# Test organization-enabled realm
curl https://dev.eworksuite.com/realms/eworksuite/.well-known/openid-configuration

# Verify organization scope in metadata
```

#### Phase 2: Organization Structure (Week 3-4)

**Tasks:**
1. Define organization naming convention
2. Map existing customers to organizations
3. Create organizations via API
4. Assign domains to organizations
5. Link existing identity providers

**Example:**
```javascript
// Migration script
const customers = await db.customers.findAll();

for (const customer of customers) {
  await createOrganization({
    name: customer.name,
    alias: customer.slug,
    domains: customer.domains,
    attributes: {
      customerId: customer.id,
      tier: customer.subscription_tier,
      createdAt: customer.created_at
    }
  });
}
```

#### Phase 3: User Migration (Week 5-6)

**Tasks:**
1. Identify users per organization
2. Add users as organization members
3. Validate email domains
4. Test authentication flows
5. Migrate admin permissions

**Migration Strategy:**

**Option A: Automated Batch Migration**
```python
# Add existing users to organizations
async def migrate_users_to_organizations():
    users = await keycloak_admin.get_users("eworksuite")

    for user in users:
        email_domain = user["email"].split("@")[1]
        org = await find_organization_by_domain(email_domain)

        if org:
            await keycloak_admin.add_organization_member(
                realm="eworksuite",
                org_id=org["id"],
                user_id=user["id"]
            )
```

**Option B: Gradual Migration (Recommended)**
- Keep existing users functional
- Add organization membership on next login
- Use invitation links for new members
- Migrate admins first, then regular users

#### Phase 4: Application Updates (Week 7-8)

**Tasks:**
1. Update frontend to request `organization` scope
2. Parse organization claims from tokens
3. Update API authorization logic
4. Add organization context to database queries
5. Update admin UI for organization management

**Code Updates:**

**Before:**
```typescript
// Old: Group-based authorization
if (!user.groups.includes('customer-acme')) {
  throw new Error('Unauthorized');
}
```

**After:**
```typescript
// New: Organization-based authorization
const org = user.organization?.['acme-corp'];
if (!org) {
  throw new Error('Unauthorized');
}
```

#### Phase 5: Testing & Validation (Week 9-10)

**Test Scenarios:**
1. ✅ User login with organization domain
2. ✅ Automatic IdP redirect
3. ✅ Token contains organization claim
4. ✅ Cross-organization isolation
5. ✅ Admin can manage organization members
6. ✅ Invitation links work
7. ✅ SSO within organization

#### Phase 6: Production Rollout (Week 11-12)

**Rollout Strategy:**
1. Deploy to production (feature flag OFF)
2. Enable for pilot customers (2-3 orgs)
3. Monitor for 1 week
4. Gradual rollout (10% → 50% → 100%)
5. Enable for all organizations
6. Deprecate old group-based approach

---

## 7. Alternative Solutions

### 7.1 If Keycloak Organizations is Not Suitable

#### Option 1: Custom Attribute-Based Multi-Tenancy

**Approach:**
```yaml
Shared Realm with Custom Attributes:
  User Attributes:
    - tenantId: "tenant-001"
    - tenantRole: "admin|user"

  Group Structure:
    - Tenant-001
      - Admins
      - Users
    - Tenant-002
      - Admins
      - Users

  Custom Mappers:
    - Add tenantId to tokens
    - Add tenantRole to tokens

  Application Logic:
    - Filter queries by tenantId
    - Validate tenantRole for admin ops
```

**Pros:**
- ✅ Works with any Keycloak version
- ✅ Maximum flexibility
- ✅ Scales to 1000s of tenants

**Cons:**
- ❌ Requires significant custom code
- ❌ No built-in isolation
- ❌ Risk of cross-tenant leakage
- ❌ Complex to audit

#### Option 2: Migration to AWS Cognito

**When to Consider:**
- Need fully managed solution
- AWS-native architecture
- Budget for per-MAU pricing

**Cognito Multi-Tenancy:**
```
User Pool per Tenant:
├── Tenant-A User Pool
│   ├── Users
│   ├── App Clients
│   └── Identity Providers
│
├── Tenant-B User Pool
│   └── ...
│
└── Central App (routes to pools)
```

**Trade-offs:**
- ✅ Fully managed
- ✅ Native AWS integration
- ✅ Complete isolation
- ❌ Higher cost at scale
- ❌ Limited customization
- ❌ Vendor lock-in

#### Option 3: Migration to Auth0

**When to Consider:**
- Need advanced CIAM features
- Budget for Auth0 pricing
- Want best-in-class UX

**Auth0 Organizations:**
```
Auth0 Tenant:
├── Organization: Acme Corp
│   ├── Members
│   ├── Connections (IdPs)
│   └── Branding
│
├── Organization: Beta Inc
│   └── ...
│
└── Shared connections
```

**Trade-offs:**
- ✅ Best-in-class CIAM
- ✅ Native organizations support
- ✅ Advanced features (attack protection, etc.)
- ❌ Expensive at scale
- ❌ Vendor lock-in
- ❌ Less control

### 7.2 Decision Matrix

```
┌─────────────────────────────────────────────────────────────────────┐
│ Solution          │ Cost │ Effort │ Isolation │ Features │ Vendor   │
│                   │      │        │           │          │ Lock-in  │
├───────────────────┼──────┼────────┼───────────┼──────────┼──────────┤
│ Keycloak Orgs     │ Low  │ Low    │ Good      │ Growing  │ None     │
│ (Recommended)     │      │        │           │          │          │
├───────────────────┼──────┼────────┼───────────┼──────────┼──────────┤
│ Realm per Tenant  │ High │ Medium │ Excellent │ Full     │ None     │
├───────────────────┼──────┼────────┼───────────┼──────────┼──────────┤
│ Custom Attributes │ Low  │ High   │ Fair      │ Custom   │ None     │
├───────────────────┼──────┼────────┼───────────┼──────────┼──────────┤
│ AWS Cognito       │ High │ High   │ Excellent │ Limited  │ High     │
├───────────────────┼──────┼────────┼───────────┼──────────┼──────────┤
│ Auth0             │ V.High│Medium │ Excellent │ Advanced │ High     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Implementation Checklist

### 8.1 Phase 1: Keycloak Organizations Setup

- [ ] Upgrade to Keycloak 25+ (or 26 for GA support)
- [ ] Enable `organization` feature flag
- [ ] Enable Organizations in realm settings
- [ ] Verify authentication flows updated
- [ ] Test identity-first login

### 8.2 Phase 2: Organization Structure

- [ ] Define organization naming convention
- [ ] Create organizations via Admin API
- [ ] Configure domains for each organization
- [ ] Set organization attributes (tenantId, tier, etc.)
- [ ] Configure redirect URLs

### 8.3 Phase 3: Identity Provider Configuration

- [ ] Link identity providers to organizations
- [ ] Configure domain-based routing
- [ ] Test automatic IdP redirects
- [ ] Configure public IdPs (if needed)
- [ ] Test first broker login flow

### 8.4 Phase 4: Member Management

- [ ] Add existing users as organization members
- [ ] Generate invitation links for new members
- [ ] Test member onboarding flows
- [ ] Configure member permissions
- [ ] Test cross-organization isolation

### 8.5 Phase 5: Token Configuration

- [ ] Add `organization` scope to clients
- [ ] Configure organization mapper
- [ ] Enable organization ID in claims
- [ ] Enable organization attributes in claims
- [ ] Test token structure

### 8.6 Phase 6: Application Integration

**Frontend:**
- [ ] Update auth library to request `organization` scope
- [ ] Parse organization claims from tokens
- [ ] Store organization context
- [ ] Update UI based on organization
- [ ] Add organization selector (if multi-org users)

**Backend:**
- [ ] Parse organization from JWT tokens
- [ ] Add organization context to request
- [ ] Filter database queries by organization
- [ ] Validate organization access
- [ ] Add organization to audit logs

### 8.7 Phase 7: Testing

- [ ] Test login flows per organization
- [ ] Test IdP redirects
- [ ] Test invitation links
- [ ] Test cross-organization isolation
- [ ] Test SSO within organization
- [ ] Performance testing with multiple orgs
- [ ] Security audit

### 8.8 Phase 8: Monitoring & Operations

- [ ] Add organization metrics
- [ ] Monitor per-org authentication rates
- [ ] Track per-org user counts
- [ ] Alert on quota exceeded
- [ ] Dashboard for organization health

---

## 9. Recommendations

### 9.1 Short-Term (Q1 2026)

**Immediate Actions:**
1. ✅ **Use Keycloak Organizations feature** (REQ-ENT-002)
   - Technology Preview acceptable for beta customers
   - Plan for GA support in Keycloak 26

2. ✅ **Implement Phase 1-4 from migration plan**
   - Enable Organizations
   - Create organization structure
   - Migrate pilot customers
   - Update applications

3. ⚠️ **Document limitations**
   - No per-org branding yet (workaround: use domains)
   - No per-org admin roles (use realm roles + custom logic)
   - Monitor Keycloak roadmap for these features

### 9.2 Medium-Term (Q2-Q3 2026)

**Actions:**
1. ✅ **Complete migration to Organizations**
   - All customers on organization model
   - Deprecate group-based approach
   - Full token-based authorization

2. ✅ **Implement custom solutions for gaps**
   - Per-org analytics dashboard
   - Quota enforcement in application
   - Custom admin UI per organization

3. ✅ **Upgrade to Keycloak 26**
   - Organizations becomes GA
   - Evaluate new features (branding, admin roles)

### 9.3 Long-Term (Q4 2026+)

**Strategic Decisions:**
1. 🔄 **Evaluate alternative IAM solutions**
   - Monitor Keycloak Organizations maturity
   - Consider Auth0/Cognito if gaps remain
   - Maintain abstraction layer for flexibility

2. 🔄 **Consider hybrid approach**
   - Organizations for 95% of customers
   - Dedicated realms for enterprise (5%)
   - Balance cost vs. isolation

### 9.4 Architecture Principles

**To Maintain Flexibility:**

1. ✅ **Abstract IAM implementation**
   ```typescript
   // Don't expose Keycloak-specific logic
   interface IAMProvider {
     getOrganization(token: Token): Organization;
     validateAccess(user: User, resource: Resource): boolean;
   }

   // Implementations: KeycloakIAM, CognitoIAM, Auth0IAM
   ```

2. ✅ **Store critical tenant data in application DB**
   - Don't rely solely on Keycloak attributes
   - Sync organization data to app database
   - Use Keycloak as authentication source

3. ✅ **Design for migration**
   - Keep abstraction layer
   - Document IAM dependencies
   - Test with mock IAM provider

---

## 10. Conclusion

### 10.1 Summary

**Recommended Approach:** **Keycloak Organizations Feature**

**Rationale:**
1. ✅ Meets 80% of REQ-ENT-002 requirements today
2. ✅ Roadmap addresses remaining 20% in KC 26
3. ✅ No vendor lock-in
4. ✅ Cost-effective (self-hosted)
5. ✅ Scales to 100s of organizations
6. ✅ Built-in security features
7. ✅ Good developer experience

**Gap Analysis:**
- ❌ Per-org branding: Use subdomain-based theming workaround
- ❌ Per-org admin roles: Custom application logic for now
- ⚠️ Technology Preview: Acceptable for phased rollout

### 10.2 Next Steps

**Immediate (Week 1-2):**
1. Setup Keycloak 25+ with Organizations feature in dev
2. Create 2-3 pilot organizations
3. Update authentication flows
4. Test identity-first login

**Short-term (Month 1-3):**
1. Complete Phase 1-4 of migration plan
2. Onboard 5-10 pilot customers
3. Update frontend/backend for organization claims
4. Monitor and gather feedback

**Medium-term (Month 4-6):**
1. Full production rollout
2. Migrate all customers to Organizations
3. Upgrade to Keycloak 26 (when GA)
4. Implement custom features for gaps

---

## Appendix A: Configuration Examples

### A.1 Organization Creation (Admin API)

```bash
# Create organization
curl -X POST https://auth.eworksuite.com/admin/realms/eworksuite/organizations \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corporation",
    "alias": "acme-corp",
    "domains": ["acme.com", "acmecorp.com"],
    "enabled": true,
    "attributes": {
      "tenantId": "tenant-001",
      "tier": "enterprise",
      "maxUsers": "500",
      "industry": "manufacturing"
    },
    "redirectUrl": "https://app.eworksuite.com/org/acme",
    "description": "Main customer organization for Acme Corp"
  }'
```

### A.2 Link Identity Provider

```bash
# Link Okta IdP to organization
curl -X POST https://auth.eworksuite.com/admin/realms/eworksuite/organizations/${ORG_ID}/identity-providers \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "identityProvider": "acme-okta",
    "domain": "acme.com",
    "hideOnLoginPage": true
  }'
```

### A.3 Add Member to Organization

```bash
# Add existing user
curl -X POST https://auth.eworksuite.com/admin/realms/eworksuite/organizations/${ORG_ID}/members \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "userId": "user-uuid-123"
  }'
```

### A.4 Generate Invitation Link

```bash
# Create invitation
curl -X POST https://auth.eworksuite.com/admin/realms/eworksuite/organizations/${ORG_ID}/invitations \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@acme.com",
    "expiresIn": 86400
  }'
```

---

## Appendix B: Code Examples

### B.1 Frontend: Organization Context Hook

```typescript
// hooks/useOrganization.ts
import { useAuth } from '@/lib/auth';

export interface Organization {
  alias: string;
  id: string;
  name?: string;
  attributes?: Record<string, any>;
}

export function useOrganization(): Organization | null {
  const { user } = useAuth();

  if (!user?.organization) {
    return null;
  }

  // Get first organization (user authenticated to)
  const orgAlias = Object.keys(user.organization)[0];
  const orgData = user.organization[orgAlias];

  return {
    alias: orgAlias,
    id: orgData.id,
    name: orgData.name,
    attributes: orgData
  };
}

// Usage in component
export function Dashboard() {
  const org = useOrganization();

  if (!org) {
    return <div>No organization context</div>;
  }

  return (
    <div>
      <h1>Welcome to {org.name}</h1>
      <p>Organization ID: {org.id}</p>
    </div>
  );
}
```

### B.2 Backend: Organization Middleware

```python
# middleware/organization.py
from fastapi import Request, HTTPException
from typing import Optional, Dict
import jwt

class OrganizationContext:
    def __init__(self, alias: str, id: str, attributes: Dict = None):
        self.alias = alias
        self.id = id
        self.attributes = attributes or {}

async def get_organization_context(request: Request) -> OrganizationContext:
    """Extract organization context from JWT token"""

    # Get token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided")

    token = auth_header[7:]  # Remove "Bearer "

    try:
        # Decode token (validate signature in production!)
        decoded = jwt.decode(token, options={"verify_signature": False})

        # Extract organization claim
        org_claim = decoded.get("organization", {})

        if not org_claim:
            raise HTTPException(
                status_code=403,
                detail="Organization context required"
            )

        # Get first organization
        org_alias = list(org_claim.keys())[0]
        org_data = org_claim[org_alias]

        return OrganizationContext(
            alias=org_alias,
            id=org_data.get("id"),
            attributes=org_data
        )

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Usage in route
from fastapi import Depends

@app.get("/api/projects")
async def get_projects(
    org: OrganizationContext = Depends(get_organization_context)
):
    # Filter projects by organization
    projects = await db.projects.find({
        "organizationId": org.id
    }).to_list()

    return projects
```

### B.3 Database Query Filtering

```python
# services/project_service.py
from typing import List
from models import Project
from middleware.organization import OrganizationContext

class ProjectService:
    def __init__(self, org_context: OrganizationContext):
        self.org = org_context

    async def list_projects(self) -> List[Project]:
        """List projects for current organization"""
        return await db.projects.find({
            "organizationId": self.org.id,
            "deleted": False
        }).to_list()

    async def get_project(self, project_id: str) -> Project:
        """Get project, ensuring it belongs to organization"""
        project = await db.projects.find_one({
            "_id": project_id,
            "organizationId": self.org.id
        })

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found or access denied"
            )

        return project

    async def create_project(self, data: ProjectCreate) -> Project:
        """Create project for organization"""
        project = Project(
            **data.dict(),
            organizationId=self.org.id,
            createdAt=datetime.utcnow()
        )

        await db.projects.insert_one(project.dict())
        return project
```

---

## Appendix C: References

### C.1 Keycloak Documentation
- [Organizations Feature Announcement](https://www.keycloak.org/2024/06/announcement-keycloak-organizations)
- [Managing Organizations](https://www.keycloak.org/docs/latest/server_admin/#_managing_organizations)
- [Authentication Flows](https://www.keycloak.org/docs/latest/server_admin/#_authentication-flows)
- [Keycloak Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/index.html)

### C.2 Related Specifications
- [eWorkSuite IAM Service Specification](01-eworksuite-iam-service.md)
- [Keycloak Authentication Flows](02-keycloak-auth-flows.md)

### C.3 Industry Standards
- [OAuth 2.0 RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [SAML 2.0](https://docs.oasis-open.org/security/saml/Post2.0/sstc-saml-tech-overview-2.0.html)

---

**Document Status:** Production Ready
**Last Review:** November 29, 2025
**Next Review:** Q1 2026 (after Keycloak 26 release)
