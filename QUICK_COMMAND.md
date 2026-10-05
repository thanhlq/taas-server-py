# QUICK COMMANDS

## Mac OS

```bash
# Kill port

lsof -i tcp:[8192]

kill -9 $(sudo lsof -t -i:8191)
kill -9 $(sudo lsof -t -i:9192)
kill -9 $(sudo lsof -t -i:7102)
```

## delete real .env files (keep committed examples)

```bash
# Print
find . -type d \( -name ".data" -o -name ".git" \) -prune -o \( -name ".env" -o -name ".env.test" \) -type f -print

# Delete
find . -type d \( -name ".data" -o -name ".git" \) -prune -o \( -name ".env" -o -name ".env.test" \) -type f -delete
```

## Fix folder owner permission

```bash
# Recursively fix folder permission for an owner user in linux

