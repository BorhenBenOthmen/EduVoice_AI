import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import SERVER_HOST, SERVER_PORT, DEBUG_MODE
from app.features.voice_session.websocket import websocket_endpoint

app = FastAPI(
    title="EduVoice AI",
    description="Real-time educational voice assistant powered by Gemini Live API",
    version="1.0.0",
)

# Mount the static directory for the test client UI
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """Serve the voice test client."""
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    """Health-check endpoint for Docker / load-balancer probes."""
    return {"status": "ok", "service": "eduvoice-ai"}


# Register the WebSocket endpoint
app.websocket("/ws")(websocket_endpoint)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=DEBUG_MODE,
    )
