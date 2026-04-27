# 🎓 EduVoice AI

**Real-time educational voice assistant** powered by **Google Gemini Live API**.  
EduVoice AI provides a full-duplex, audio-to-audio WebSocket streaming experience tailored for Tunisian students — from primary school through Baccalauréat.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start (Docker)](#quick-start-docker)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Integration with Main Backend](#integration-with-main-backend)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Grade Levels](#grade-levels)

---

## Overview

EduVoice AI is a **microservice** that acts as an intelligent voice tutor. It receives audio from a client (mobile app or web browser), streams it to Google's Gemini Live API, and forwards the AI-generated audio response back to the client in real time.

The service is designed to be **deployed as a standalone Docker container** and integrated into the main backend infrastructure via a shared Docker network or reverse proxy.

---

## Architecture

```
┌──────────────┐         WebSocket (ws://)         ┌──────────────────┐
│              │  ──── Audio PCM 16kHz (mic) ────▶ │                  │
│  Flutter App │                                    │  EduVoice AI     │
│  or Browser  │  ◀── Audio PCM 24kHz (speaker) ── │  (FastAPI + WS)  │
│              │  ◀── JSON control messages ─────── │                  │
└──────────────┘                                    └────────┬─────────┘
                                                             │
                                                    Gemini Live API
                                                    (audio-to-audio)
                                                             │
                                                    ┌────────▼─────────┐
                                                    │  Google Gemini   │
                                                    │  (Cloud)         │
                                                    └──────────────────┘
```

---

## Features

| Feature | Description |
|---|---|
| 🎙️ **Full-Duplex Audio** | Continuous mic streaming + simultaneous AI playback |
| ⚡ **Barge-In (Interruption)** | Interrupt the AI mid-sentence — Gemini's server-side VAD detects speech and cancels the current response |
| 🎓 **Grade-Aware Persona** | Adapts tone, vocabulary, and curriculum to the student's educational level |
| 🌐 **Multilingual** | Supports Arabic, French, and English interactions |
| 🔄 **API Key Failover** | Automatic fallback to a secondary Gemini API key |
| 🏥 **Health Check** | Built-in `/health` endpoint for Docker and load balancer probes |
| 🧪 **Test Client** | Built-in browser-based test UI at `/` |

---

## Project Structure

```
EduVoice_AI/
├── main.py                          # FastAPI application entry point
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Container build instructions
├── docker-compose.yml               # Orchestration config
├── .env.example                     # Environment variable template
├── .gitignore                       # Git ignore rules
├── .dockerignore                    # Docker build exclusions
│
├── app/
│   ├── core/
│   │   ├── config.py                # Environment config loader
│   │   └── logger.py                # Structured logging setup
│   │
│   ├── domain/
│   │   └── models.py                # Student data model
│   │
│   └── features/
│       └── voice_session/
│           ├── websocket.py         # WebSocket handler (Gemini bridge)
│           ├── system_prompt.py     # Dynamic prompt builder
│           └── prompts/
│               ├── base.txt         # Base system prompt template
│               ├── primary.txt      # Primary school profile
│               ├── middle.txt       # Middle school profile
│               ├── secondary_1.txt  # 1st year secondary profile
│               ├── secondary_2_3_lettres.txt  # 2nd-3rd year Lettres
│               └── bac.txt          # Bac Lettres (final year)
│
└── static/
    └── index.html                   # Browser-based test client
```

---

## Prerequisites

- **Docker** ≥ 20.10 and **Docker Compose** ≥ 2.0
- A **Google AI Studio API Key** — get one at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

---

## Quick Start (Docker)

### 1. Clone the repository

```bash
git clone https://github.com/BorhenBenOthmen/EduVoice_AI.git
cd EduVoice_AI
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your Gemini API keys:

```env
GEMINI_API_KEY=AIzaSy...your-key-here
GEMINI_API_KEY_FALLBACK=AIzaSy...your-fallback-key   # optional
```

### 3. Build and run

```bash
docker-compose up -d --build
```

### 4. Verify

```bash
# Check container health
docker-compose ps

# Test the health endpoint
curl http://localhost:8000/health
# → {"status":"ok","service":"eduvoice-ai"}
```

### 5. Open the test client

Navigate to **http://localhost:8000** in your browser.

---

## Quick Start (Local Development)

```bash
# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run the server
python main.py
```

The server will start on **http://0.0.0.0:8000** by default.

---

## Integration with Main Backend

### Network Configuration

| Setting | Value |
|---|---|
| **Service Name** | `eduvoice-ai` |
| **Internal Port** | `8000` |
| **Protocol** | WebSocket (`ws://`) |
| **Health Check** | `GET /health` |
| **WebSocket Path** | `/ws` |

### Option 1: Docker Network (Recommended)

If your main backend runs in Docker Compose, add EduVoice AI to the **same Docker network**:

**In `docker-compose.yml` of EduVoice AI**, uncomment the network section:

```yaml
services:
  eduvoice-ai:
    # ... existing config ...
    networks:
      - backend-network

networks:
  backend-network:
    external: true
    name: your-main-backend-network-name   # ← replace with your actual network
```

Then from your main backend containers, reach this service at:

```
ws://eduvoice-ai:8000/ws
```

### Option 2: Port Mapping

If the main backend is **not containerized**, map the port and connect directly:

```
ws://YOUR_SERVER_IP:8000/ws
```

### Option 3: Reverse Proxy (Nginx)

Add to your Nginx config:

```nginx
location /ai/ws {
    proxy_pass http://eduvoice-ai:8000/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;  # 24h for long-lived WebSocket
}

location /ai/health {
    proxy_pass http://eduvoice-ai:8000/health;
}
```

### Connecting from the Flutter App

Update the WebSocket URL in your Flutter app's `GeminiRoutingService`:

```dart
// For Docker network (via reverse proxy)
final wsUrl = 'ws://your-domain.com/ai/ws?name=$name&grade_level=$grade&primary_language=$lang';

// For direct connection
final wsUrl = 'ws://SERVER_IP:8000/ws?name=$name&grade_level=$grade&primary_language=$lang';
```

---

## API Reference

### `GET /health`

Health-check endpoint.

**Response:**
```json
{
  "status": "ok",
  "service": "eduvoice-ai"
}
```

### `GET /`

Serves the built-in browser test client.

### `WS /ws`

Full-duplex audio WebSocket endpoint.

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"Student"` | Student's name |
| `grade_level` | string | `"primary_4"` | Student's grade level (see table below) |
| `primary_language` | string | `"Arabic"` | Preferred language (`Arabic`, `French`, `English`) |
| `course_names` | string | `""` | Comma-separated list of enrolled courses |

**Protocol:**

| Direction | Type | Format |
|---|---|---|
| Client → Server | Binary | Raw PCM Int16 @ 16kHz mono |
| Server → Client | Binary | `4-byte generation_id (big-endian)` + PCM Int16 @ 24kHz mono |
| Server → Client | JSON | `{"type": "interrupt", "generation_id": N}` |
| Server → Client | JSON | `{"type": "turn_complete", "generation_id": N}` |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | — | Primary Google Gemini API key |
| `GEMINI_API_KEY_FALLBACK` | No | — | Fallback API key (auto-failover) |
| `SERVER_HOST` | No | `0.0.0.0` | Bind address |
| `SERVER_PORT` | No | `8000` | Server port |
| `DEBUG_MODE` | No | `True` | Enable hot-reload in development |
| `LOG_LEVEL` | No | `DEBUG` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `MODEL_NAME` | No | `gemini-3.1-flash-live-preview` | Primary Gemini model |
| `MODEL_NAME_FALLBACK` | No | `gemini-2.5-flash` | Fallback Gemini model |

---

## Grade Levels

Supported `grade_level` values:

| Key | French Label | Arabic Label |
|---|---|---|
| `primary_4` | 4ème année primaire | السنة الرابعة ابتدائي |
| `primary_5` | 5ème année primaire | السنة الخامسة ابتدائي |
| `primary_6` | 6ème année primaire | السنة السادسة ابتدائي |
| `middle_7` | 7ème année de base | السنة السابعة أساسي |
| `middle_8` | 8ème année de base | السنة الثامنة أساسي |
| `middle_9` | 9ème année de base | التاسعة أساسي |
| `secondary_1` | 1ère année secondaire | السنة الأولى ثانوي |
| `secondary_2_lettres` | 2ème année secondaire — Lettres | السنة الثانية ثانوي — شعبة الآداب |
| `secondary_3_lettres` | 3ème année secondaire — Lettres | السنة الثالثة ثانوي — شعبة الآداب |
| `secondary_4_lettres` | 4ème année secondaire — Bac Lettres | السنة الرابعة ثانوي — بكالوريا آداب |

---

## License

This project is proprietary software developed for the EduVoice platform.

---

<p align="center">
  Built with ❤️ for Tunisian students
</p>
