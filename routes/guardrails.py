import re
import os
import json
import httpx
from typing import Tuple
from pathlib import Path

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GUARDRAIL_MODEL = "openai/gpt-4o-mini"

# load guardrails prompt from file
PROMPT_FILE = Path(__file__).parent.parent / "guardrails_prompt.txt"
try:
    GUARDRAIL_SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8").strip()
except FileNotFoundError:
    print("WARNING: guardrails_prompt.txt not found — using minimal fallback")
    GUARDRAIL_SYSTEM_PROMPT = (
        "You are a content safety classifier. "
        "Return JSON: {is_safe: bool, category: str, "
        "confidence: float, reason: str, severity: str}"
    )

# ═══════════════════════════════════════
# LAYER 1 — RULE BASED (instant, free)
# ═══════════════════════════════════════

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"forget\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?)",
    r"you\s+are\s+now\s+(DAN|jailbreak|unrestricted|free|evil|unfiltered)",
    r"pretend\s+(you\s+)?(have\s+)?no\s+(rules?|restrictions?|limits?|guidelines?)",
    r"act\s+as\s+(an?\s+)?(unrestricted|unfiltered|uncensored|evil|harmful)",
    r"(override|bypass|disable|remove)\s+(your\s+)?(safety|filter|guardrail|restriction)",
    r"new\s+(system\s+)?instructions?\s*:",
    r"(system|admin|developer|root)\s*:\s*(ignore|forget|override|disable)",
    r"<\s*system\s*>",
    r"\[INST\].*?(override|ignore|forget)",
    r"do\s+anything\s+now",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode\s+(enabled|on|activated)",
    r"ADMIN\s+OVERRIDE",
    r"from\s+now\s+on\s+you\s+(will|are|must)",
    r"your\s+(true|real|actual)\s+(self|nature|purpose)",
    r"without\s+(ethical\s+)?(restrictions?|limits?|guidelines?|filters?)",
]

CRITICAL_HARMFUL_PATTERNS = [
    r"how\s+to\s+(make|build|create|synthesize)\s+(a\s+)?(bomb|explosive|weapon|poison|bioweapon)",
    r"child\s+(porn|pornography|sexual\s+abuse|exploitation|molestation)",
    r"(CSAM|child\s+sexual\s+abuse\s+material)",
    r"step\s+by\s+step.{0,30}(kill|murder|assassinate)\s+.{0,30}(person|people|individual)",
    r"how\s+to\s+synthesize\s+(meth|heroin|fentanyl|sarin|VX|nerve\s+agent)",
    r"instructions\s+for\s+(suicide|self.harm)\s+method",
]

SYSTEM_ATTACK_PATTERNS = [
    r"repeat\s+(this\s+)?word\s+\d{4,}",
    r"print\s+[\"']\w+[\"']\s+\d{4,}\s+times",
    r"(infinite|endless)\s+(loop|recursion)",
]

MAX_MESSAGE_LENGTH = 12000
MIN_MESSAGE_LENGTH = 1


def check_rule_based(message: str) -> Tuple[bool, str, str, str]:
    """
    Layer 1: Fast rule-based checks.
    Returns (is_safe, category, reason, severity)
    """
    if len(message) < MIN_MESSAGE_LENGTH:
        return False, "SYSTEM_ATTACK", "Empty message", "low"

    if len(message) > MAX_MESSAGE_LENGTH:
        return False, "SYSTEM_ATTACK", \
            f"Message exceeds {MAX_MESSAGE_LENGTH} character limit", "medium"

    message_lower = message.lower()

    # check critical harmful patterns first (highest priority)
    for pattern in CRITICAL_HARMFUL_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE | re.DOTALL):
            return False, "HARMFUL_CONTENT", \
                "Message contains critically harmful content", "critical"

    # check prompt injection
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return False, "PROMPT_INJECTION", \
                "Prompt injection pattern detected", "high"

    # check system attack patterns
    for pattern in SYSTEM_ATTACK_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return False, "SYSTEM_ATTACK", \
                "System abuse pattern detected", "medium"

    return True, "safe", "ok", "none"


# ═══════════════════════════════════════
# LAYER 2 — LLM BASED (accurate)
# ═══════════════════════════════════════

async def check_llm_based(message: str) -> Tuple[bool, str, str, float, str]:
    """
    Layer 2: LLM-based safety classification.
    Returns (is_safe, category, reason, confidence, severity)
    """
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prism-ai",
            "X-Title": "Prism"
        }

        payload = {
            "model": GUARDRAIL_MODEL,
            "messages": [
                {"role": "system", "content": GUARDRAIL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Classify this message:\n\n\"{message[:3000]}\""
                }
            ],
            "temperature": 0,
            "max_tokens": 150
        }

        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            print(f"Guardrail API error: {response.status_code} — defaulting to safe")
            return True, "safe", "Guardrail API unavailable", 0.5, "none"

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        result = json.loads(content)

        is_safe = result.get("is_safe", True)
        category = result.get("category", "safe")
        reason = result.get("reason", "No reason provided")
        confidence = float(result.get("confidence", 0.5))
        severity = result.get("severity", "none")

        # only block if confidence is high enough
        if not is_safe and confidence < 0.60:
            print(f"Guardrail: low confidence ({confidence}) — defaulting to safe")
            is_safe = True
            category = "safe"
            severity = "none"

        return is_safe, category, reason, confidence, severity

    except json.JSONDecodeError as e:
        print(f"Guardrail JSON parse error: {e} — defaulting to safe")
        return True, "safe", "Parse error — defaulting to safe", 0.5, "none"

    except httpx.TimeoutException:
        print("Guardrail timeout — defaulting to safe")
        return True, "safe", "Timeout — defaulting to safe", 0.5, "none"

    except Exception as e:
        print(f"Guardrail error: {type(e).__name__}: {e} — defaulting to safe")
        return True, "safe", "Error — defaulting to safe", 0.5, "none"


# ═══════════════════════════════════════
# MAIN GUARDRAIL CHECK
# ═══════════════════════════════════════

async def check_message(message: str) -> dict:
    """
    Main guardrail entry point.
    Runs both layers and returns a safety verdict.

    Returns:
    {
        is_safe: bool,
        category: str,
        reason: str,
        confidence: float,
        severity: str,
        layer: str  ("rule_based" or "llm_based" or "passed")
    }
    """
    # layer 1: rule-based (fast, free)
    rule_safe, rule_category, rule_reason, rule_severity = \
        check_rule_based(message)

    if not rule_safe:
        print(f"Guardrail BLOCKED (rule-based): {rule_category} — {rule_reason}")
        return {
            "is_safe": False,
            "category": rule_category,
            "reason": rule_reason,
            "confidence": 0.99,
            "severity": rule_severity,
            "layer": "rule_based"
        }

    # layer 2: LLM-based (accurate, catches nuanced attacks)
    llm_safe, llm_category, llm_reason, llm_confidence, llm_severity = \
        await check_llm_based(message)

    if not llm_safe:
        print(f"Guardrail BLOCKED (llm-based): {llm_category} "
              f"({llm_confidence:.2f}) — {llm_reason}")
        return {
            "is_safe": False,
            "category": llm_category,
            "reason": llm_reason,
            "confidence": llm_confidence,
            "severity": llm_severity,
            "layer": "llm_based"
        }

    # passed both layers
    return {
        "is_safe": True,
        "category": "safe",
        "reason": "Message passed all safety checks",
        "confidence": llm_confidence,
        "severity": "none",
        "layer": "passed"
    }


def get_blocked_response(category: str, severity: str) -> str:
    """
    Returns a warm, human response when a message is blocked.
    Matches the emotional intelligence of Prism.
    """
    responses = {
        "PROMPT_INJECTION": (
            "I noticed that message was trying to change how I work. "
            "I am here to help with coding, writing, and research — "
            "let me know what you actually need and I will do my best!"
        ),
        "JAILBREAK_ATTEMPT": (
            "That one is not something I can help with. "
            "I work best when we keep things straightforward — "
            "what is the real task I can help you with today?"
        ),
        "HARMFUL_CONTENT": (
            "I am not able to help with that request. "
            "If there is something else on your mind — "
            "a coding problem, writing task, or research question — "
            "I am here and happy to help."
        ),
        "PII_EXTRACTION": (
            "I keep all user data private and secure. "
            "I cannot share information about other users or sessions. "
            "Is there something else I can help you with?"
        ),
        "SYSTEM_ATTACK": (
            "That request is not something I can process. "
            "Let me know what you are actually trying to accomplish "
            "and I will find the best way to help."
        ),
        "TARGETED_HARASSMENT": (
            "I am not able to help create content that targets or "
            "harms specific people. "
            "Happy to help with something constructive instead!"
        ),
    }

    return responses.get(
        category,
        "I am not able to help with that particular request. "
        "Let me know what else I can do for you!"
    )