# Keycloak Into SaaS

## SaaS Mapping

1. The High-Level Mapping Blueprint

| B2B SaaS Concept | Keycloak Equivalent | Scope & Purpose |
| --- | --- | --- |
| The Entire Platform | 1 Realm (e.g., `saas-production`) | Holds your global configurations, shared OIDC clients, and central user database. |
| The Tenant (e.g., Acme Corp) | 1 Organization | Represents the customer company. Manages their identity provider (SSO) and email routing domains. |
| Internal Departments (e.g., Sales, Eng) | Organization Groups | Local organizational hierarchy. Only exists within the context of that specific tenant. |
| System Permissions (e.g., `write:billing`) | Client / Realm Roles | Global feature flags/capabilities defined at the SaaS platform level. |

2. Deep Dive: Keycloak Organizations (The Tenant)

```bash
┌─────────────────────────────────────────┐
│        SaaS Production Realm            │
├─────────────────────────────────────────┤
│          [ OIDC Client: App ]           │
│                                         │
│  ┌──────────────────┐ ┌──────────────┐  │
│  │  Organization A  │ │Organization B│  │
│  │   (Acme Corp)    │ │(Globex Inc)  │  │
│  ├──────────────────┤ ├──────────────┤  │
│  │  • Acme Okta IdP │ │• Globex SAML │  │
│  │  • acme.com      │ │• globex.com  │  │
│  └──────────────────┘ └──────────────┘  │
└─────────────────────────────────────────┘
```

- SSO & Identity Federation: If Acme Corp wants enterprise SSO, you link their identity provider (like Okta or Entra ID) to Organization A.
- Email Domain Routing: You assign the domain acme.com to Organization A. When a user enters bob@acme.com on your unified login page, Keycloak automatically routes them to Acme's Okta login screen.
- Managed vs. Unmanaged Users: Users logging in via Okta are "Managed Members" (if they get deleted in Okta, they lose SaaS access). Guest contractors logging in via standard email/password are "Unmanaged Members".

3. Deep Dive: Organization Groups (Team Structure)

- Rather than using global realm-level groups—which bleed across tenants—use Organization Groups (introduced in Keycloak 26.6) to create isolated structures.

- Isolated Hierarchies: Organization A and Organization B can both have a group named /Engineering/Backend. They are completely isolated, ensuring no cross-tenant naming collisions or data leakage.

- Dynamic Mapping via IdP: You can map incoming claims from a tenant’s Okta profile directly to their internal Organization Groups. For example, if Okta passes department=sales, Keycloak can automatically drop the user into the tenant's local /Sales group.

4. Deep Dive: Roles (What Users Can Do)
In a pure B2B SaaS architecture, you should never hardcode tenant names into your roles (e.g., acme_billing_admin). Roles should be generic and platform-wide.
Define Global Roles: Create Client Roles in Keycloak that represent functional access (e.g., billing-admin, editor, viewer).
Bind Roles Contextually: You map these global roles to the tenant's Organization Groups.
Example: Map the global client role billing-admin to Organization A's /Finance group.

5. How Your Backend Consumes This (The JWT)

When a user logs in, your SaaS backend receives a JSON Web Token (JWT). Keycloak's dedicated Organization Mapper injects the multi-tenant context directly into this token.
Your token will include a payload structured like this:

```json
{
  "sub": "usr_98234",
  "email": "alice@acme.com",
  "organizations": {
    "acme-corp": {
      "id": "org_acme_123",
      "attributes": {
        "tier": ["enterprise"]
      },
      "groups": ["/Finance", "/Engineering/Backend"]
    }
  },
  "resource_access": {
    "my-saas-app": {
      "roles": ["billing-admin", "developer"]
    }
  }
}
```
