import os
import io
import tempfile
import subprocess
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
from db.auth import verify_token

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SUPPORTED_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
DEFAULT_VOICE = "nova"


def convert_to_wav(audio_bytes: bytes, input_format: str = "webm") -> bytes:
    """
    Converts audio bytes to WAV using FFmpeg.
    Browser MediaRecorder typically outputs webm/ogg.
    Whisper works best with WAV or MP3.
    """
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f".{input_format}",
            delete=False
        ) as input_file:
            input_file.write(audio_bytes)
            input_path = input_file.name

        output_path = input_path.replace(f".{input_format}", ".wav")

        result = subprocess.run([
            "ffmpeg",
            "-i", input_path,
            "-ar", "16000",      # 16kHz sample rate (Whisper optimal)
            "-ac", "1",          # mono channel
            "-f", "wav",
            output_path,
            "-y",                # overwrite if exists
            "-loglevel", "error" # suppress ffmpeg output
        ], capture_output=True, timeout=30)

        if result.returncode != 0:
            print(f"FFmpeg error: {result.stderr.decode()}")
            # try returning original bytes if conversion fails
            return audio_bytes

        with open(output_path, "rb") as f:
            wav_bytes = f.read()

        # cleanup temp files
        os.unlink(input_path)
        os.unlink(output_path)

        return wav_bytes

    except Exception as e:
        print(f"Audio conversion error: {e}")
        return audio_bytes


# ═══════════════════════════════════════
# TRANSCRIPTION (Speech → Text)
# ═══════════════════════════════════════

@router.post("/voice/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token)
):
    """
    Transcribes audio to text using OpenAI Whisper.
    Accepts webm, wav, mp3, mp4, m4a, ogg, flac.
    Returns transcribed text.
    """
    try:
        # read uploaded audio
        audio_bytes = await file.read()

        if len(audio_bytes) == 0:
            raise HTTPException(
                status_code=400,
                detail="Audio file is empty"
            )

        print(f"Transcribing audio: {len(audio_bytes)} bytes, "
              f"type: {file.content_type}, "
              f"filename: {file.filename}")

        # detect format from content type or filename
        content_type = file.content_type or ""
        filename = file.filename or "audio.webm"

        if "webm" in content_type or filename.endswith(".webm"):
            input_format = "webm"
        elif "ogg" in content_type or filename.endswith(".ogg"):
            input_format = "ogg"
        elif "mp4" in content_type or filename.endswith(".mp4"):
            input_format = "mp4"
        elif "m4a" in content_type or filename.endswith(".m4a"):
            input_format = "m4a"
        elif "wav" in content_type or filename.endswith(".wav"):
            input_format = "wav"
        elif "mp3" in content_type or filename.endswith(".mp3"):
            input_format = "mp3"
        else:
            input_format = "webm"  # default

        # convert to WAV if not already
        if input_format not in ["wav", "mp3"]:
            print(f"Converting {input_format} → wav")
            audio_bytes = convert_to_wav(audio_bytes, input_format)

        # check audio is not silent (basic size check)
        if len(audio_bytes) < 1000:
            return {"text": "", "duration": 0}

        # send to Whisper
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.wav"

        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
            response_format="verbose_json"
        )

        text = transcript.text.strip()
        duration = getattr(transcript, "duration", 0)

        print(f"Transcription: '{text[:100]}...' "
              f"({duration:.1f}s)")

        return {
            "text": text,
            "duration": duration
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Transcription error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}"
        )


# ═══════════════════════════════════════
# TEXT TO SPEECH (Text → Audio)
# ═══════════════════════════════════════

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = DEFAULT_VOICE
    speed: Optional[float] = 1.0


@router.post("/voice/speak")
async def text_to_speech(
    request: TTSRequest,
    user_id: str = Depends(verify_token)
):
    """
    Converts text to speech using OpenAI TTS.
    Streams audio back as MP3.
    """
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=400,
                detail="Text cannot be empty"
            )

        voice = request.voice or DEFAULT_VOICE
        if voice not in SUPPORTED_VOICES:
            voice = DEFAULT_VOICE

        # strip markdown before TTS
        text = strip_markdown_for_tts(request.text)

        # limit text length
        if len(text) > 4000:
            text = text[:4000] + "..."

        print(f"TTS: {len(text)} chars, voice={voice}")

        speed = max(0.25, min(4.0, request.speed or 1.0))

        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=speed
        )

        audio_bytes = response.content

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=speech.mp3",
                "Content-Length": str(len(audio_bytes))
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"TTS error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"TTS failed: {str(e)}"
        )


@router.get("/voice/voices")
async def list_voices(user_id: str = Depends(verify_token)):
    """Returns available TTS voices."""
    return {
        "voices": SUPPORTED_VOICES,
        "default": DEFAULT_VOICE,
        "descriptions": {
            "alloy": "Neutral and balanced",
            "echo": "Deep and authoritative",
            "fable": "Warm and storytelling",
            "onyx": "Strong and confident",
            "nova": "Energetic and clear",
            "shimmer": "Soft and expressive"
        }
    }


def strip_markdown_for_tts(text: str) -> str:
    """
    Strips markdown syntax before sending to TTS.
    Keeps natural sentence flow.
    """
    import re

    # remove code blocks entirely
    text = re.sub(r'```[\s\S]*?```', '[code block]', text)

    # remove inline code
    text = re.sub(r'`[^`]+`', '', text)

    # remove headers (keep text)
    text = re.sub(r'#{1,6}\s+', '', text)

    # remove bold and italic (keep text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)

    # remove links (keep label)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # remove images
    text = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', text)

    # remove horizontal rules
    text = re.sub(r'\n---+\n', '\n', text)

    # remove bullet points (keep text)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)

    # remove numbered lists markers
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text