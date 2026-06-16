# QUICK COMMANDS

## Mac OS

```bash
# Kill port

lsof -i tcp:[8192]

kill -9 $(sudo lsof -t -i:8191)
kill -9 $(sudo lsof -t -i:9192)
```
