# Test Authentication

```bash

# Register users
curl -X 'POST' \
  'http://localhost:8191/api/v1/auth/signup' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "firstName": "Ngoc",
  "lastName": "LE",
  "email": "ngocle1401@gmail.com",
  "password": "Abcd@1234",
  "organizationName": "Noi Cho",
  "preferredRegion": "US"
}'

```
