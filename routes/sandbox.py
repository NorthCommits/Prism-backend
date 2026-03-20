import httpx
import os
from typing import Optional

SANDBOX_URL = os.getenv("SANDBOX_URL", "https://hamthunder-judge0-sandbox.hf.space")

SUPPORTED_LANGUAGES = ["python", "javascript", "typescript", "bash"]


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