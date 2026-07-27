#!/bin/bash

start=$(date +%s.%N)

# 1
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "tuanpham@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Tuan PHAM",
  "username": "tp214813",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'

# 2
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "vinhpham@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Vinh PHAM",
  "username": "pxvinh214",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'

# 3
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "sangau@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Sang",
  "username": "un1234",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'

# 4
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "ngocle1401@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Ngoc LE",
  "username": "socwow214",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'

# 5
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "miki123@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Miki",
  "username": "m12345",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'

# 6
curl -X 'POST' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "email": "rok123@gmail.com",
  "password": "Bamevietnam@214",
  "name": "Rok",
  "username": "rok9321",
  "is_root_account": true,
  "status": "active",
  "email_verified": true,
  "properties": {"profile": "https://avatars.githubusercontent.com/u/12345678?v=4"}
}'


end=$(date +%s.%N)
echo "------------------------------------"
echo "total wall clock: $(echo "$end - $start" | bc)s"