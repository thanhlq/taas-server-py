# Iam Oauth Specifications

## References

 - [Authlib](https://docs.authlib.org/en/stable/)

## Feature Lists

- [ ] Fully working OIDC / OAuth 2 provider
- [ ] PAM logins via custom PAM + NSS modules
- [ ] Hiqlite or Postgres as database
- [ ] Fast and efficient with low footprint
- [ ] Secure default values
- [ ] Highly configurable
- [ ] High-Availability
- [ ] True passwordless accounts with E-Mail + Magic Link + Passkey
- [ ] Dedicated Admin UI
- [ ] Account dashboard UI for each user with self-service
- [ ] OpenID Connect Dynamic Client Registration
- [ ] OpenID Connect RP Initiated Logout
- [ ] OpenID Connect Backchannel Logout
- [ ] OAuth 2 Device Authorization Grant flow
- [ ] Upstream Authentication Providers (Login with ...)
- [ ] DPoP tokens for decentralized login flows
- [ ] Ephemeral, dynamic clients for decentralized login flows
- [ ] SCIM v2 for downstream clients
- [ ] All End-User facing sites support i18n server-side translation with the possibility to add more languages
- [ ] Simple per-client branding for the login page
- [ ] Custom roles
- [ ] Custom groups
- [ ] Custom scopes
- [ ] Custom user attributes
- [ ] User attribute binding to custom scopes
- [ ] Optional user-editable custom attributes
- [ ] Configurable password policy
- [ ] Admin API Keys with fine-grained access rights
- [ ] Events and alerting system
- [ ] Optional event persistence
- [ ] Dedicated forward_auth endpoint, in addition to the existing userinfo, with support for configurable trusted auth headers
- [ ] Optional event notifications via: E-Mail, Matrix, Slack
- [ ] Optional Force MFA for the Admin UI
- [ ] Optional Force MFA for each client
- [ ] Restrict logins to clients via group prefix
- [ ] Additional encryption inside the database for the most critical entries
- [ ] Automatic database backups with configurable retention and auto-cleanup (Hiqlite only)
- [ ] auto-encrypted backups (Hiqlite only)
- [ ] Ability to push Hiqlite backups to S3 storage
- [ ] auto-restore Hiqlite backups from file or s3
- [ ] Username enumeration prevention
- [ ] Login / Password hashing rate limiting
- [ ] Session client peer IP binding
- [ ] IP blacklisting feature
- [ ] Auto-IP blacklisting for login endpoints
- [ ] Brute-Force and Credential Stuffing detection
- [ ] Geolocation-based access restriction
- [ ] Namespaced K/V store for arbitrary JSON data
- [ ] Argon2ID with config helper UI utility
- [ ] Housekeeping schedulers and cron jobs
- [ ] JSON Web Key Set (JWKS) autorotation feature
- [ ] Account conversions between traditional password and Passkey only
- [ ] Optional open user registration
- [ ] Optional user registration domain restriction
- [ ] App version update checker
- [ ] SwaggerUI documentation
- [ ] Configurable E-Mail templates for NewPassword + ResetPassword events
- [ ] Prometheus /metrics endpoint on separate port
- [ ] No-Setup migrations between different databases (Yes, even between Hiqlite and Postgres)
- [ ] Hot-Reload TLS certificates without restart
- [ ] Can serve a basic webid document
- [ ] Experimental FedCM support
