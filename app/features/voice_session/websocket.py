import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from app.core.config import GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK, MODEL_NAME, MODEL_NAME_FALLBACK
from app.core.logger import logger
from app.domain.models import Student
from app.features.voice_session.system_prompt import build_system_instruction

primary_client = genai.Client(api_key=GEMINI_API_KEY)
fallback_client = genai.Client(api_key=GEMINI_API_KEY_FALLBACK) if GEMINI_API_KEY_FALLBACK else None

@asynccontextmanager
async def get_gemini_session(config):
    try:
        async with primary_client.aio.live.connect(model=MODEL_NAME, config=config) as session:
            yield session
    except Exception as e:
        logger.warning(f"Primary API key failed with error: {e}. Trying fallback...")
        if fallback_client:
            async with fallback_client.aio.live.connect(model=MODEL_NAME_FALLBACK, config=config) as session:
                yield session
        else:
            raise

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_ip = websocket.client.host

    # Read Student parameters from query
    query_params = websocket.query_params
    student_name = query_params.get("name", "Student")
    grade_level = query_params.get("grade_level", "primary_4")
    primary_language = query_params.get("primary_language", "Arabic")
    course_names_raw = query_params.get("course_names", "")
    course_names = [c.strip() for c in course_names_raw.split(",") if c.strip()] if course_names_raw else []

    student = Student(name=student_name, grade_level=grade_level, primary_language=primary_language, course_names=course_names)
    system_instruction_text = build_system_instruction(student)

    logger.info(f"WebSocket connection established with {client_ip} for Student: {student.name} ({student.grade_level})")

    # Configuration for the Live API
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO], # Force Gemini to reply with Audio
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=system_instruction_text)]
        )
    )

    # ---------------------------------------------------------------------------
    # Barge-in state: generation_id is incremented on every interruption so
    # the frontend can discard stale audio chunks from a cancelled generation.
    # ---------------------------------------------------------------------------
    generation_id: int = 0

    async def _send_json(msg: dict) -> None:
        """Helper to send a JSON text frame to the browser, swallowing errors."""
        try:
            await websocket.send_text(json.dumps(msg))
        except Exception:
            pass  # Connection may already be closing

    try:
        # Establish the persistent Live connection with Google
        async with get_gemini_session(config) as session:
            logger.info("Successfully connected to Gemini Live API.")

            # TASK 1: Read audio bytes from Browser -> Send to Gemini
            # The mic stream NEVER stops — this is critical for Gemini's
            # server-side VAD to detect barge-in while the model is speaking.
            audio_chunk_count = 0

            async def receive_from_browser():
                nonlocal audio_chunk_count
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        audio_chunk_count += 1
                        if audio_chunk_count % 100 == 0:
                            logger.debug(f"Sent {audio_chunk_count} audio chunks to Gemini.")
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=data,
                                mime_type="audio/pcm;rate=16000"
                            )
                        )
                except WebSocketDisconnect:
                    logger.info(f"Browser disconnected after {audio_chunk_count} audio chunks.")
                except Exception as e:
                    logger.error(f"Error reading from browser: {e}", exc_info=True)

            # TASK 2: Read responses from Gemini -> Forward to Browser
            # Handles audio chunks, turn_complete, and INTERRUPTION signals.
            async def receive_from_gemini():
                nonlocal generation_id
                turn_count = 0
                try:
                    while True:
                        async for response in session.receive():
                            server_content = response.server_content

                            if server_content is None:
                                logger.debug(f"Gemini non-content message: {type(response).__name__}")
                                continue

                            # -------------------------------------------------
                            # BARGE-IN: Gemini's server-side VAD detected the
                            # user speaking while the model was generating.
                            # The server has already cancelled generation.
                            # We must tell the frontend to flush its playback.
                            # -------------------------------------------------
                            if getattr(server_content, 'interrupted', False):
                                generation_id += 1
                                logger.info(
                                    f"⚡ Barge-in detected — Gemini interrupted. "
                                    f"New generation_id={generation_id}"
                                )
                                await _send_json({
                                    "type": "interrupt",
                                    "generation_id": generation_id
                                })
                                continue

                            # Forward audio chunks to the browser, tagged with
                            # the current generation_id (4-byte big-endian header).
                            if server_content.model_turn is not None:
                                for part in server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        header = generation_id.to_bytes(4, 'big')
                                        await websocket.send_bytes(
                                            header + part.inline_data.data
                                        )

                            # Turn completion — natural end of the model's response
                            if server_content.turn_complete:
                                turn_count += 1
                                logger.info(f"Gemini turn #{turn_count} complete — ready for next question.")
                                await _send_json({
                                    "type": "turn_complete",
                                    "generation_id": generation_id
                                })

                except asyncio.CancelledError:
                    logger.info(f"Gemini receive task cancelled after {turn_count} turns.")
                except Exception as e:
                    logger.error(f"Error receiving from Gemini: {e}", exc_info=True)

            # Run both tasks concurrently
            browser_task = asyncio.create_task(receive_from_browser())
            gemini_task = asyncio.create_task(receive_from_gemini())

            try:
                await browser_task
            except Exception:
                pass
            finally:
                gemini_task.cancel()
                try:
                    await gemini_task
                except asyncio.CancelledError:
                    pass

    except Exception as e:
        logger.error(f"Live API Connection Failed: {e}", exc_info=True)
    finally:
        logger.info(f"WebSocket session closed for {client_ip}")
        try:
            await websocket.close()
        except:
            pass
