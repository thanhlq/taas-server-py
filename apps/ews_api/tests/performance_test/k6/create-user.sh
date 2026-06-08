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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
}'


# repeat 1

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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "username": "m123458",
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
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
  "username": "rok123459",
  "phone": null,
  "isSuperuser": false,
  "isActive": true,
  "isVerified": false,
  "properties": null
}'

end=$(date +%s.%N)
echo "------------------------------------"
echo "total wall clock: $(echo "$end - $start" | bc)s"