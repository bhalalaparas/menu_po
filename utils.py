import os
from fastapi import Header, HTTPException

STATIC_API_TOKEN = os.getenv("STATIC_API_TOKEN", "qwerty123")

def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.replace("Bearer ", "")

    if token != STATIC_API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")