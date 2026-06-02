# BonVoyage Backend Agents

AI-powered travel planning backend built with **FastAPI** and **CrewAI**. Deploys as a single Python serverless function on **Vercel**.

## Agents

| Agent | Role |
|---|---|
| **City Selection** | Recommends destinations based on interests, traits, and budget |
| **Local Expert** | Suggests places, restaurants, and activities at a destination |
| **Flight Expert** | Estimates realistic flight costs between origin and destination |
| **Travel Concierge** | Builds a paced daily itinerary from the list of places |

## API Endpoints

- `GET /` — Health check
- `GET /health` — Status and timestamp
- `POST /plan` — Full trip planning pipeline (SSE stream)
- `POST /refine` — Refine an existing itinerary with natural language

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # Add your MISTRAL_API_KEY
uvicorn main:app --reload --port 8001
```

## Deploy to Vercel

```bash
vercel --prod
```

## Environment Variables

Set `MISTRAL_API_KEY` in Vercel project settings.
