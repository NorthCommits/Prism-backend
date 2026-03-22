import os
import json
import httpx
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from db.supabase import get_supabase
from db.auth import verify_token

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
SCORING_MODEL = "openai/gpt-4o-mini"

SCORING_SYSTEM_PROMPT = """
You are a conversation analyst for Prism, an AI copilot.

Analyze the conversation and return a JSON score object.

Score these dimensions:

1. productivity_score (1-10):
   - 10: Task fully completed, clear outcome achieved
   - 7-9: Mostly completed, good progress made
   - 4-6: Partial progress, some value gained
   - 1-3: Minimal progress, mostly exploration

2. complexity_score (1-10):
   - 10: Very complex (architecture design, research, multi-step)
   - 7-9: Complex (debugging, analysis, detailed writing)
   - 4-6: Moderate (code help, explanations, drafting)
   - 1-3: Simple (quick questions, basic tasks)

3. satisfaction_score (1-10):
   Based on conversation tone and completion:
   - 10: User got exactly what they needed
   - 7-9: User seemed satisfied
   - 4-6: Partial satisfaction
   - 1-3: User seemed frustrated or unmet

4. category: ONE of these exact strings:
   "coding" | "writing" | "research" | "analysis" | 
   "learning" | "planning" | "creative" | "general"

5. topics: Array of 1-3 key topics (short strings)
   e.g. ["Python", "FastAPI", "REST API"]
   e.g. ["Machine Learning", "Neural Networks"]
   e.g. ["Email Writing", "Professional Communication"]

6. time_saved_minutes: Estimated minutes saved vs doing manually
   Be realistic: simple task=5, complex task=30-60, research=60-120

7. summary: One sentence describing what was accomplished.
   e.g. "Debugged a Python authentication error in FastAPI"
   e.g. "Researched and summarized LLM architectures"
   e.g. "Drafted a professional email for a job application"

Respond ONLY with valid JSON:
{
  "productivity_score": 8,
  "complexity_score": 6,
  "satisfaction_score": 9,
  "category": "coding",
  "topics": ["Python", "FastAPI"],
  "time_saved_minutes": 25,
  "summary": "Built a REST API endpoint with authentication"
}
""".strip()


async def score_conversation(
    conversation_id: str,
    user_id: str,
    messages: List[dict]
) -> Optional[dict]:
    """
    Analyzes a conversation and generates productivity scores.
    Called as a background task after conversations.
    """
    try:
        if not messages or len(messages) < 2:
            return None

        # build conversation text for analysis
        conv_text = ""
        for msg in messages[-10:]:  # last 10 messages
            role = msg.get("role", "").upper()
            content = msg.get("content", "")[:300]
            conv_text += f"{role}: {content}\n\n"

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prism-ai",
            "X-Title": "Prism"
        }

        payload = {
            "model": SCORING_MODEL,
            "messages": [
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": f"Score this conversation:\n\n{conv_text}"}
            ],
            "temperature": 0,
            "max_tokens": 300
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            print(f"Scoring API error: {response.status_code}")
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        scores = json.loads(content)

        # validate required fields
        required = [
            "productivity_score", "complexity_score",
            "satisfaction_score", "category", "topics",
            "time_saved_minutes", "summary"
        ]
        for field in required:
            if field not in scores:
                print(f"Missing field in scores: {field}")
                return None

        # clamp scores to valid range
        for score_field in ["productivity_score", "complexity_score", "satisfaction_score"]:
            scores[score_field] = max(1, min(10, int(scores[score_field])))

        scores["time_saved_minutes"] = max(0, int(scores.get("time_saved_minutes", 5)))

        # save to database
        client_db = get_supabase()

        # check if score already exists for this conversation
        existing = (
            client_db.table("conversation_scores")
            .select("id")
            .eq("conversation_id", conversation_id)
            .execute()
        )

        message_count = len(messages)

        if existing.data:
            # update existing score
            result = client_db.table("conversation_scores").update({
                "productivity_score": scores["productivity_score"],
                "complexity_score": scores["complexity_score"],
                "satisfaction_score": scores["satisfaction_score"],
                "category": scores["category"],
                "topics": scores["topics"],
                "time_saved_minutes": scores["time_saved_minutes"],
                "summary": scores["summary"],
                "message_count": message_count,
                "scored_at": datetime.utcnow().isoformat()
            }).eq("conversation_id", conversation_id).execute()
        else:
            # insert new score
            result = client_db.table("conversation_scores").insert({
                "user_id": user_id,
                "conversation_id": conversation_id,
                "productivity_score": scores["productivity_score"],
                "complexity_score": scores["complexity_score"],
                "satisfaction_score": scores["satisfaction_score"],
                "category": scores["category"],
                "topics": scores["topics"],
                "time_saved_minutes": scores["time_saved_minutes"],
                "summary": scores["summary"],
                "message_count": message_count
            }).execute()

        print(f"Scored conversation {conversation_id}: productivity={scores['productivity_score']}, category={scores['category']}")
        return scores

    except Exception as e:
        print(f"Scoring error: {type(e).__name__}: {e}")
        return None


# ═══════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════

@router.get("/scores/summary")
async def get_scores_summary(
    days: int = 30,
    user_id: str = Depends(verify_token)
):
    """
    Returns productivity summary for the last N days.
    Used for the profile dashboard.
    """
    try:
        client = get_supabase()
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()

        response = (
            client.table("conversation_scores")
            .select("*")
            .eq("user_id", user_id)
            .gte("scored_at", since)
            .order("scored_at", desc=True)
            .execute()
        )

        scores = response.data or []

        if not scores:
            return {
                "total_conversations": 0,
                "avg_productivity": 0,
                "avg_complexity": 0,
                "avg_satisfaction": 0,
                "total_time_saved_minutes": 0,
                "total_messages": 0,
                "category_breakdown": {},
                "top_topics": [],
                "daily_scores": [],
                "weekly_report": None
            }

        # calculate averages
        avg_productivity = sum(s["productivity_score"] for s in scores) / len(scores)
        avg_complexity = sum(s["complexity_score"] for s in scores) / len(scores)
        avg_satisfaction = sum(s["satisfaction_score"] for s in scores) / len(scores)
        total_time_saved = sum(s["time_saved_minutes"] for s in scores)
        total_messages = sum(s["message_count"] for s in scores)

        # category breakdown
        category_breakdown = {}
        for s in scores:
            cat = s.get("category", "general")
            category_breakdown[cat] = category_breakdown.get(cat, 0) + 1

        # top topics
        topic_counts = {}
        for s in scores:
            for topic in (s.get("topics") or []):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
        top_topics = sorted(
            topic_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        # daily scores for chart (last 30 days)
        daily_scores = {}
        for s in scores:
            day = s["scored_at"][:10]  # YYYY-MM-DD
            if day not in daily_scores:
                daily_scores[day] = {
                    "date": day,
                    "count": 0,
                    "productivity": [],
                    "time_saved": 0
                }
            daily_scores[day]["count"] += 1
            daily_scores[day]["productivity"].append(s["productivity_score"])
            daily_scores[day]["time_saved"] += s["time_saved_minutes"]

        # average productivity per day
        daily_chart = []
        for day, data in sorted(daily_scores.items()):
            daily_chart.append({
                "date": data["date"],
                "count": data["count"],
                "avg_productivity": round(
                    sum(data["productivity"]) / len(data["productivity"]), 1
                ),
                "time_saved": data["time_saved"]
            })

        # most productive day of week
        day_of_week = {}
        for s in scores:
            try:
                dt = datetime.fromisoformat(s["scored_at"].replace("Z", "+00:00"))
                dow = dt.strftime("%A")
                if dow not in day_of_week:
                    day_of_week[dow] = []
                day_of_week[dow].append(s["productivity_score"])
            except Exception:
                pass

        best_day = None
        best_day_score = 0
        for dow, dow_scores in day_of_week.items():
            avg = sum(dow_scores) / len(dow_scores)
            if avg > best_day_score:
                best_day_score = avg
                best_day = dow

        # weekly report
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        this_week = [s for s in scores if s["scored_at"] >= week_ago]
        weekly_report = None

        if this_week:
            week_time_saved = sum(s["time_saved_minutes"] for s in this_week)
            week_productivity = sum(
                s["productivity_score"] for s in this_week
            ) / len(this_week)

            weekly_report = {
                "conversations": len(this_week),
                "avg_productivity": round(week_productivity, 1),
                "time_saved_minutes": week_time_saved,
                "time_saved_hours": round(week_time_saved / 60, 1),
                "top_category": max(
                    set(s["category"] for s in this_week),
                    key=lambda c: sum(
                        1 for s in this_week if s["category"] == c
                    )
                ) if this_week else "general",
                "best_day": best_day
            }

        return {
            "total_conversations": len(scores),
            "avg_productivity": round(avg_productivity, 1),
            "avg_complexity": round(avg_complexity, 1),
            "avg_satisfaction": round(avg_satisfaction, 1),
            "total_time_saved_minutes": total_time_saved,
            "total_time_saved_hours": round(total_time_saved / 60, 1),
            "total_messages": total_messages,
            "category_breakdown": category_breakdown,
            "top_topics": [
                {"topic": t, "count": c} for t, c in top_topics
            ],
            "daily_scores": daily_chart,
            "weekly_report": weekly_report,
            "best_day": best_day,
            "days": days
        }

    except Exception as e:
        print(f"Scores summary error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scores/recent")
async def get_recent_scores(
    limit: int = 10,
    user_id: str = Depends(verify_token)
):
    """Returns recent conversation scores."""
    try:
        client = get_supabase()

        response = (
            client.table("conversation_scores")
            .select("*")
            .eq("user_id", user_id)
            .order("scored_at", desc=True)
            .limit(limit)
            .execute()
        )

        return response.data or []

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scores/conversation/{conversation_id}")
async def get_conversation_score(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    """Returns score for a specific conversation."""
    try:
        client = get_supabase()

        response = (
            client.table("conversation_scores")
            .select("*")
            .eq("conversation_id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not response.data:
            return None

        return response.data[0]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))