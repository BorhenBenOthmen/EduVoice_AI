import asyncio
import json
import base64
from contextlib import asynccontextmanager
from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
import httpx

from app.core.config import (
    GEMINI_API_KEY,
    GEMINI_API_KEY_FALLBACK,
    MODEL_NAME,
    MODEL_NAME_FALLBACK,
    DJANGO_BACKEND_URL,
)
from app.core.logger import logger
from app.domain.models import Student
from app.features.voice_session.system_prompt import build_system_instruction

primary_client = genai.Client(api_key=GEMINI_API_KEY)
fallback_client = genai.Client(api_key=GEMINI_API_KEY_FALLBACK) if GEMINI_API_KEY_FALLBACK else None

# ---------------------------------------------------------------------------
# Gemini Tool Declaration — Voice-Driven App Navigation
# ---------------------------------------------------------------------------
NAVIGATE_APP_CONTENT_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="navigate_app_content",
            description=(
                "Navigate the app to show educational content. "
                "Call this when the user asks to open, browse, or list "
                "lessons, podcasts, cultural records, or radio stations."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "content_type": types.Schema(
                        type=types.Type.STRING,
                        enum=["lesson", "podcast", "culture", "radio"],
                        description="The type of content to navigate to.",
                    ),
                    "subject": types.Schema(
                        type=types.Type.STRING,
                        # We FORCE the AI to pick from this exact list
                        enum=[
                            "اللغة العربية",
                            "Education Civique",
                            "Education et pensée Islamique",
                            "Philosophie",
                            "Histoire & Géographie",
                            "Français",
                            "Anglais",
                            "Italien",
                            "Allemand",
                            "Espagnol",
                            "Mathématiques",
                            "Sciences physiques",
                            "Sciences de la vie et de la terre",
                            "Informatique",
                            "Education Artistique",
                            "Education Musicale",
                            "Animation Théâtrale",
                            "Education Technique"
                        ],
                        description="The exact subject name. You MUST translate the user's request into one of these exact values.",
                    ),
                    "specific_lesson_name": types.Schema(
                        type=types.Type.STRING,
                        description="Optional specific lesson or item name to open.",
                    ),
                },
                required=["content_type"],
            ),
        )
    ]
)


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
    auth_token = query_params.get("token", "")  # <-- FIX 1: Extract auth token

    course_names_raw = query_params.get("course_names", "")
    course_names =[c.strip() for c in course_names_raw.split(",") if c.strip()] if course_names_raw else[]

    student = Student(name=student_name, grade_level=grade_level, course_names=course_names)
    system_instruction_text = build_system_instruction(student)

    logger.info(f"WebSocket connection established with {client_ip} for Student: {student.name} ({student.grade_level})")

    # Configuration for the Live API — with tool injection
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],  # Force Gemini to reply with Audio
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=system_instruction_text)]
        ),
        tools=[NAVIGATE_APP_CONTENT_TOOL],
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
            # Handles audio chunks, turn_complete, INTERRUPTION signals,
            # and TOOL CALLS for voice-driven navigation.
            async def receive_from_gemini():
                nonlocal generation_id
                turn_count = 0
                try:
                    while True:
                        async for response in session.receive():

                            # -------------------------------------------------
                            # TOOL CALL: Gemini wants to invoke a function
                            # instead of (or before) producing audio.
                            # -------------------------------------------------
                            tool_call = response.tool_call
                            if tool_call is not None:
                                for fc in tool_call.function_calls:
                                    await _handle_tool_call(
                                        session, fc, grade_level
                                    )
                                continue

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
                                    f"[BARGE-IN] Gemini interrupted. "
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

            # ---------------------------------------------------------------
            # Tool-call handler: fetch data from Django, push UI command to
            # Flutter, and send a toolResponse back to Gemini.
            # ---------------------------------------------------------------
            async def _handle_tool_call(session, fc, grade_level: str):
                """Process a single FunctionCall from Gemini."""
                fn_name = fc.name
                args = fc.args or {}
                call_id = fc.id

                logger.info(f"[TOOL] Call received: {fn_name}")

                if fn_name != "navigate_app_content":
                    logger.warning(f"Unknown tool call: {fn_name} — ignoring.")
                    return

                content_type = args.get("content_type", "lesson")
                subject = args.get("subject")
                specific_lesson_name = args.get("specific_lesson_name")

                # -----------------------------------------------------------
                # DYNAMIC URL BUILDING & BRANCHING
                # -----------------------------------------------------------
                base_url = "https://radio.backend.ecocloud.tn"

                # 1. UI Route map (Where Flutter navigates)
                route_map = {
                    "lesson": "/lessons",
                    "podcast": "/podcasts",
                    "culture": "/culture",
                    "radio": "/radio"
                }
                route_string = route_map.get(content_type, f"/{content_type}s")

                # 2. Extract user_id from token
                user_id = "1"
                if auth_token:
                    try:
                        payload_b64 = auth_token.split(".")[1]
                        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                        payload_json = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
                        user_id = str(payload_json.get("user_id", "1"))
                    except Exception:
                        pass

                # 3. Backend Endpoint map (Where Django gets the data)
                endpoint_map = {
                    "lesson":  f"/lesson/search/{user_id}/",
                    "podcast": f"/ai/podcasts/{user_id}/",
                    "culture": f"/ai/cultural-activities/{user_id}/",
                    "radio":   f"/ai/emissions/{user_id}/",
                }
                target_url = f"{base_url}{endpoint_map.get(content_type, f'/ai/lessons/{user_id}/')}"

                request_params = {}
                if content_type == "lesson":
                    request_params["limit"] = 100
                    request_params["offset"] = 0
                    if subject:
                        request_params["subject"] = subject

                # --- Fetch from Django backend ---
                try:
                    headers = {}
                    if auth_token:
                        headers["Authorization"] = f"Bearer {auth_token}"

                    logger.debug(f"[FETCH] Requesting data from: {target_url}")

                    async with httpx.AsyncClient(timeout=5.0) as http_client:
                        django_resp = await http_client.get(
                            target_url,
                            params=request_params,
                            headers=headers,
                        )
                        django_resp.raise_for_status()
                        payload = django_resp.json()

                    # Safely unwrap Django pagination if it exists
                    if isinstance(payload, dict):
                        if "items" in payload:
                            payload = payload["items"]
                        elif "results" in payload:
                            payload = payload["results"]
                        elif "data" in payload:
                            payload = payload["data"]

                    # -----------------------------------------------------------
                    # MANUAL FILTERING & DIRECT PLAY LOGIC
                    # -----------------------------------------------------------
                    if isinstance(payload, list):

                        # A. MANUAL LEVEL FILTER (Only applies to lessons)
                        if content_type == "lesson":
                            level_map = {
                                "primary_4": "4 ème année primaire",
                                "primary_5": "5 ème année primaire",
                                "primary_6": "6 ème année primaire",
                                "middle_7": "7ème année de base",
                                "middle_8": "8ème année de base",
                                "middle_9": "9ème année de base",
                                "secondary_1": "1ère année secondaire",
                                "secondary_2": "2ème année secondaire",
                                "secondary_3": "3ème année secondaire",
                                "secondary_4": "4ème année secondaire",
                            }
                            target_level = level_map.get(grade_level, "").lower()
                            if target_level:
                                temp_payload = []
                                for item in payload:
                                    try:
                                        item_level = item.get("module", {}).get("level", {}).get("name", "").lower()
                                        if target_level in item_level:
                                            temp_payload.append(item)
                                    except Exception:
                                        pass
                                # Always overwrite, even if empty!
                                payload = temp_payload
                                logger.info(f"[FILTER] Level filter applied. {len(payload)} items remain.")

                            # B. MANUAL SUBJECT FILTER (lessons only)
                            if subject and len(payload) > 0:
                                target_subject = subject.lower().strip()
                                temp_payload = []
                                for item in payload:
                                    try:
                                        item_subj = item.get("module", {}).get("subject", {}).get("name", "").lower()
                                        if target_subject == item_subj:
                                            temp_payload.append(item)
                                    except Exception:
                                        pass
                                # Always overwrite, even if empty!
                                payload = temp_payload
                                logger.info(f"[FILTER] Subject filter applied. {len(payload)} items remain.")

                            # C. DIRECT PLAY FILTER (lessons only)
                            if specific_lesson_name and len(payload) > 0:
                                target_name = specific_lesson_name.lower().strip()
                                best_match = None
                                for item in payload:
                                    try:
                                        item_name = item.get("name", "").lower()
                                        if target_name in item_name or item_name in target_name:
                                            best_match = item
                                            break
                                    except Exception:
                                        pass

                                if best_match:
                                    payload = [best_match]
                                    route_string = f"/{content_type}_player"
                                    logger.info(f"[DIRECT PLAY] Match found. Routing to {route_string}")
                                else:
                                    payload = []  # Specific lesson requested but not found
                                    logger.warning(f"[DIRECT PLAY] '{specific_lesson_name}' not found. List is now empty.")

                        else:
                            # Podcast / Culture / Radio — NO filters applied (yet)
                            logger.info(f"[FILTER] Skipping all filters for content_type='{content_type}'. {len(payload)} raw items.")

                    items_found = len(payload) if isinstance(payload, list) else 1

                    # -----------------------------------------------------------
                    # CONDITIONAL UI NAVIGATION
                    # -----------------------------------------------------------
                    if items_found > 0:
                        # Push UI navigation command to Flutter client
                        await _send_json({
                            "type": "ui_navigation",
                            "route": route_string,
                            "payload": payload,
                        })
                        logger.info(f"[SUCCESS] Sent ui_navigation to Flutter: {route_string} ({items_found} items)")
                    else:
                        logger.info("[EMPTY] 0 items found. Skipping UI navigation. Gemini will inform the user.")

                    # -------------------------------------------------------
                    # BULLETPROOF GOOGLE SDK WRAPPER
                    # -------------------------------------------------------
                    try:
                        if items_found > 0:
                            tool_result = {
                                "result": "success",
                                "items_found": items_found,
                            }
                        else:
                            # Tell Gemini explicitly: nothing was found, say so out loud.
                            tool_result = {
                                "result": "not_found",
                                "items_found": 0,
                                "message": (
                                    f"No {content_type} content was found"
                                    + (f" for subject '{subject}'" if subject else "")
                                    + ". Do NOT navigate. "
                                    "Inform the user clearly that this content does not exist yet."
                                ),
                            }
                            logger.info(f"[TOOL RESPONSE] Sending not_found to Gemini for '{content_type}' / subject='{subject}'")

                        tool_response = types.LiveClientToolResponse(
                            function_responses=[
                                types.FunctionResponse(
                                    name=fn_name,
                                    id=call_id,
                                    response=tool_result,
                                )
                            ]
                        )
                        await session.send(input=tool_response)
                        logger.info(f"[SUCCESS] toolResponse sent to Gemini (result={tool_result['result']})")
                    except Exception as sdk_error:
                        # If Google's SDK crashes, WE IGNORE IT so the server stays alive!
                        logger.warning(f"Google SDK tool_response suppressed: {sdk_error}")

                except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
                    logger.error(f"[ERROR] Django backend request failed: {exc}", exc_info=True)
                    try:
                        error_response = types.LiveClientToolResponse(
                            function_responses=[
                                types.FunctionResponse(
                                    name=fn_name,
                                    id=call_id,
                                    response={
                                        "result": "error",
                                        "message": "Backend unavailable or Not Found",
                                    },
                                )
                            ]
                        )
                        await session.send(input=error_response)
                        logger.warning("[WARN] Error toolResponse sent to Gemini — session remains alive.")
                    except Exception:
                        pass

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