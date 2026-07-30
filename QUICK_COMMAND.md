# QUICK COMMANDS

## Mac OS

```bash
# Kill port

lsof -i tcp:[8192]

kill -9 $(sudo lsof -t -i:8191)
kill -9 $(sudo lsof -t -i:9192)
kill -9 $(sudo lsof -t -i:7002)
```

## delete all .env files

```bash
# Print
find . -type d \( -name ".data" -o -name ".git" \) -prune -o -name ".env" -type f -print

# Delete
find . -type d \( -name ".data" -o -name ".git" \) -prune -o -name ".env" -type f -delete
```

## Fix folder owner permission

```bash
# Recursively fix folder permission for an owner user in linux


