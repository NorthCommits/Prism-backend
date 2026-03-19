import os
import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """
    Verifies Supabase JWT token and returns user_id.
    """
    token = credentials.credentials
    supabase_url = os.getenv("SUPABASE_URL")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": os.getenv("SUPABASE_KEY")
                }
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token"
            )

        user_data = response.json()
        return user_data["id"]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Token verification failed: {str(e)}"
        )