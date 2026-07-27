# SaaS Schema

```text
Tenant (1)
  ├── (N) Organizations
  │       └── (N) Teams
  └── (N) Users ── (N) [Org Memberships] ── (N) [Team Memberships]
```
