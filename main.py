from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from pydantic import BaseModel
import uvicorn
import boto3
import json
import sys
import logging
import os
import time
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info(f"Environment loaded from: {env_path}")
logger.info(f"AWS Region: {os.environ.get('AWS_REGION', '(not set)')}")
logger.info(f"Webshare Secret Name: {os.environ.get('WEBSHARE_SECRET_NAME', '(not set)')}")
logger.info(f"Using direct Webshare credentials: {bool(os.environ.get('WEBSHARE_USERNAME'))}")

app = FastAPI(title="YouTube Transcript API", version="1.0.0")


def get_webshare_credentials() -> tuple[str, str]:
    """
    Resolve Webshare proxy credentials.

    Priority:
      1. WEBSHARE_USERNAME / WEBSHARE_PASSWORD env vars (local dev / staging)
      2. AWS Secrets Manager (production — uses WEBSHARE_SECRET_NAME + AWS_REGION)
    """
    username = os.environ.get("WEBSHARE_USERNAME")
    password = os.environ.get("WEBSHARE_PASSWORD")

    if username and password:
        logger.info("Using Webshare credentials from environment variables")
        return username, password

    # Fall back to AWS Secrets Manager
    secret_name = os.environ.get("WEBSHARE_SECRET_NAME")
    region_name = os.environ.get("AWS_REGION")

    if not secret_name or not region_name:
        raise RuntimeError(
            "Webshare credentials not found. Set WEBSHARE_USERNAME + WEBSHARE_PASSWORD "
            "env vars, or set WEBSHARE_SECRET_NAME + AWS_REGION for Secrets Manager."
        )

    logger.info(f"Fetching Webshare credentials from Secrets Manager: {secret_name}")
    try:
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)

        if "SecretString" not in response:
            raise RuntimeError("Secret string not found in Secrets Manager response")

        secret = json.loads(response["SecretString"])
        logger.info("Successfully retrieved Webshare credentials from Secrets Manager")
        return secret["username"], secret["password"]

    except Exception as e:
        logger.error(f"Error retrieving Webshare credentials: {e}", exc_info=True)
        raise


async def fetch_transcript_with_retry(video_id: str, languages: list, max_retries: int = 3) -> list:
    """Fetch transcript with exponential backoff retry."""
    last_error = None
    for attempt in range(max_retries):
        try:
            username, password = get_webshare_credentials()
            proxy_config = WebshareProxyConfig(proxy_username=username, proxy_password=password)
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
            transcript_list = ytt_api.list(video_id)

            # Try each requested language in order
            transcript = None
            for lang in languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    logger.info(f"Found transcript in language: {lang}")
                    break
                except Exception:
                    continue

            # Fall back to English
            if transcript is None:
                transcript = transcript_list.find_transcript(['en'])
                logger.info("Using English transcript as fallback")

            transcript_data = transcript.fetch()
            logger.info(f"Successfully retrieved transcript ({len(transcript_data)} segments) on attempt {attempt + 1}")
            return transcript_data

        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            # Don't retry on these — they're definitive failures
            raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Transcript fetch attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {max_retries} attempts failed. Last error: {e}", exc_info=True)

    raise last_error


async def list_transcripts_with_retry(video_id: str, max_retries: int = 3) -> list:
    """List available transcripts with exponential backoff retry."""
    last_error = None
    for attempt in range(max_retries):
        try:
            username, password = get_webshare_credentials()
            proxy_config = WebshareProxyConfig(proxy_username=username, proxy_password=password)
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
            transcript_list = ytt_api.list(video_id)

            transcripts = [
                {
                    "language": t.language,
                    "language_code": t.language_code,
                    "is_generated": t.is_generated,
                    "is_translatable": t.is_translatable,
                }
                for t in transcript_list
            ]
            logger.info(f"Successfully listed {len(transcripts)} transcripts on attempt {attempt + 1}")
            return transcripts

        except (TranscriptsDisabled, VideoUnavailable):
            # Don't retry on these — they're definitive failures
            raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"List transcripts attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {max_retries} list attempts failed. Last error: {e}", exc_info=True)

    raise last_error


class TranscriptRequest(BaseModel):
    video_id: str
    languages: list[str] = ["en"]


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/transcript")
async def get_transcript(request: TranscriptRequest):
    try:
        logger.info(f"Transcript request for video_id: {request.video_id}, languages: {request.languages}")

        transcript_data = await fetch_transcript_with_retry(request.video_id, request.languages)
        return {"transcript": transcript_data}

    except TranscriptsDisabled:
        logger.error(f"Transcripts disabled for video {request.video_id}")
        raise HTTPException(status_code=404, detail="Transcripts are disabled for this video")
    except NoTranscriptFound:
        logger.error(f"No transcript found for video {request.video_id} in {request.languages}")
        raise HTTPException(
            status_code=404,
            detail=f"No transcript found for this video in languages: {request.languages}"
        )
    except VideoUnavailable:
        logger.error(f"Video {request.video_id} is unavailable")
        raise HTTPException(status_code=404, detail="Video is unavailable")
    except Exception as e:
        logger.error(f"Error fetching transcript: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/transcript/list/{video_id}")
async def list_transcripts(video_id: str):
    try:
        logger.info(f"Listing transcripts for video: {video_id}")

        transcripts = await list_transcripts_with_retry(video_id)
        return {"available_transcripts": transcripts}

    except TranscriptsDisabled:
        logger.error(f"Transcripts disabled for video {video_id}")
        raise HTTPException(status_code=404, detail="Transcripts are disabled for this video")
    except VideoUnavailable:
        logger.error(f"Video {video_id} is unavailable")
        raise HTTPException(status_code=404, detail="Video is unavailable")
    except Exception as e:
        logger.error(f"Error listing transcripts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting uvicorn on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
