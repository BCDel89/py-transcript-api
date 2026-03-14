# py-transcript-api

Lightweight FastAPI microservice that fetches YouTube transcripts using [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) via Webshare rotating proxies.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/transcript` | Fetch transcript for a video |
| GET | `/transcript/list/{video_id}` | List available transcripts for a video |

### POST `/transcript`

```json
{
  "video_id": "dQw4w9WgXcQ",
  "languages": ["en"]
}
```

Response:
```json
{
  "transcript": [
    { "text": "...", "start": 0.0, "duration": 1.5 },
    ...
  ]
}
```

## Configuration

All secrets are managed via **Doppler** (`sage-server` project). See `.env.example` for the full list.

### Required Secrets (add to Doppler)

| Key | Description |
|-----|-------------|
| `WEBSHARE_USERNAME` | Webshare proxy username |
| `WEBSHARE_PASSWORD` | Webshare proxy password |

### Optional (production only — uses AWS Secrets Manager instead)

| Key | Description |
|-----|-------------|
| `WEBSHARE_SECRET_NAME` | AWS Secrets Manager secret name |
| `AWS_REGION` | AWS region (default: `us-east-1`) |

The app checks `WEBSHARE_USERNAME`/`WEBSHARE_PASSWORD` first. If unset, it falls back to Secrets Manager (production path via IAM role — no explicit AWS keys needed).

## Local Development

```bash
cp .env.example .env
# Fill in WEBSHARE_USERNAME and WEBSHARE_PASSWORD

# Option A: Docker Compose
docker compose up

# Option B: Direct
pip install -r requirements.txt
python main.py
```

## Staging (Coolify)

1. Create a new Coolify app pointing to this repo, `main` branch
2. Set env vars in Coolify (or connect Doppler):
   - `WEBSHARE_USERNAME`
   - `WEBSHARE_PASSWORD`
3. Deploy:
```bash
./scripts/deploy-coolify.sh <coolify_app_uuid>
```

## Production (AWS)

Deployed via CDK (ECS Fargate). Uses IAM instance role to access Secrets Manager — no explicit AWS keys needed in the container.
