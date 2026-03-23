import httpx
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from db.auth import verify_token

router = APIRouter()

SANDBOX_URL = os.getenv("SANDBOX_URL", "https://hamthunder-judge0-sandbox.hf.space")

SUPPORTED_LANGUAGES = ["python", "javascript", "typescript", "bash"]


class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    stdin: Optional[str] = ""


async def execute_code(
    code: str,
    language: str = "python",
    stdin: Optional[str] = ""
) -> dict:
    """
    Executes code in the Prism sandbox.
    Returns stdout, stderr, exit_code, timed_out.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{SANDBOX_URL}/execute",
                json={
                    "language": language,
                    "code": code,
                    "stdin": stdin or "",
                    "timeout": 10
                }
            )

        if response.status_code != 200:
            return {
                "stdout": "",
                "stderr": f"Sandbox error: {response.text}",
                "exit_code": 1,
                "timed_out": False
            }

        return response.json()

    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Sandbox connection error: {str(e)}",
            "exit_code": 1,
            "timed_out": False
        }


@router.post("/sandbox/execute")
async def execute_code_endpoint(
    request: ExecuteRequest,
    user_id: str = Depends(verify_token)
):
    """
    Exposed API endpoint for code execution.
    Called directly by the frontend Run button in CodeBlock.
    """
    try:
        language = request.language.lower()

        # normalize language aliases
        language_aliases = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "sh": "bash",
            "shell": "bash"
        }
        language = language_aliases.get(language, language)

        if language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language: {language}. "
                       f"Supported: {SUPPORTED_LANGUAGES}"
            )

        if not request.code or not request.code.strip():
            raise HTTPException(
                status_code=400,
                detail="Code cannot be empty"
            )

        print(f"Executing {language} code ({len(request.code)} chars) "
              f"for user {user_id}")

        result = await execute_code(
            code=request.code,
            language=language,
            stdin=request.stdin or ""
        )

        print(f"Execution complete: exit_code={result.get('exit_code')}, "
              f"stdout={len(result.get('stdout', ''))} chars, "
              f"timed_out={result.get('timed_out')}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Execute endpoint error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))