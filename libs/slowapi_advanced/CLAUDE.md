# Project

This project is enhanced from https://github.com/laurentS/slowapi

- But improved with latest limits lib and not linked to fastapi anymore.
- This library can be used for fastapi, litestar,... for rate limitting feature.
- 

Examples for fastapi configuration:

```python
from fastapi import FastAPI, Request
from slowapi_advanced import Limiter, _rate_limit_exceeded_handler
from slowapi_advanced.util import get_remote_address
from slowapi_advanced.errors import RateLimitExceeded

# 1. Initialize the Limiter
# key_func determines how to group requests (by IP address here)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI()

# 2. Attach limiter to app state and register error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 3. Apply rate limiting to a specific route
# IMPORTANT: The endpoint must accept 'request: Request' as an argument
@app.get("/items")
@limiter.limit("5/minute")
async def read_items(request: Request):
    return {"message": "Hello, World!"}
```
