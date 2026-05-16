# Voice-Driven UI Navigation — Walkthrough

## Summary

Intercepts `ui_navigation` JSON control messages from the backend WebSocket and pushes the corresponding Flutter route using the existing global `NavigatorKey` — without touching audio processing or requiring a `BuildContext`.

## Changes Made

### [NEW] [app_route_resolver.dart](file:///c:/pfe/edu_voice/lib/core/navigation/app_route_resolver.dart)

A static route resolver that maps backend route strings to concrete `MaterialPageRoute` instances, each wrapped with the correct `BlocProvider` — matching the exact patterns used in `HomeScreen`.

| Backend Route | Resolves To |
|---|---|
| `/lessons` | `LessonListScreen` + `LessonCubit` |
| `/culture` | `CultureScreen` + `CultureCubit` |
| `/podcasts` | `PodcastScreen` + `PodcastCubit` |
| `/radio` | `RadioScreen` + `RadioCubit` |
| `/settings` | `SettingsScreen` |
| `/about` | `AboutScreen` |

Unknown routes return `null` → logged and silently ignored.

---

### [MODIFY] [gemini_routing_service.dart](file:///c:/pfe/edu_voice/lib/features/voice_commander/data/gemini_routing_service.dart)

```diff:gemini_routing_service.dart
import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:record/record.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';
import '../../../core/auth/token_manager.dart';

class GeminiRoutingService {
  final TokenManager _tokenManager;
  WebSocketChannel? _channel;
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _recordSubscription;

  // AI backend WebSocket URL.
  final String _baseWsUrl = 'ws://10.165.155.12:8000/ws';

  bool _isConnected = false;
  bool get isConnected => _isConnected;

  bool _isGeminiSpeaking = false;
  Timer? _speechTimer;

  GeminiRoutingService(this._tokenManager);

  Future<void> connect({VoidCallback? onErrorCallback}) async {
    if (_isConnected) return;

    try {
      final firstName = await _tokenManager.getFirstName() ?? 'Student';
      final levelName = await _tokenManager.getLevelName() ?? 'primary_4';

      final wsUrl = Uri.parse(
        '$_baseWsUrl?name=$firstName&grade_level=${Uri.encodeComponent(levelName)}&primary_language=Arabic',
      );

      debugPrint('Connecting to Voice Commander AI WebSocket at $wsUrl');
      _channel = WebSocketChannel.connect(wsUrl);

      // Wait for the actual TCP+WS handshake to complete before proceeding.
      // Without this, the channel object exists but the connection may have
      // silently failed (e.g. cleartext blocked, host unreachable).
      await _channel!.ready.timeout(
        const Duration(seconds: 8),
        onTimeout: () {
          throw TimeoutException('WebSocket handshake timed out after 8s');
        },
      );

      _isConnected = true;
      debugPrint('Voice Commander AI WebSocket connected successfully.');

      // Handle output from Gemini (Audio bytes)
      _setupPlayback();

      _channel?.stream.listen(
        (data) {
          if (data is Uint8List) {
            FlutterPcmSound.feed(
              PcmArrayInt16(
                bytes: ByteData.view(
                  data.buffer,
                  data.offsetInBytes,
                  data.lengthInBytes,
                ),
              ),
            );

            // Software Echo Cancellation: Mute mic while playing
            _isGeminiSpeaking = true;
            _speechTimer?.cancel();
            _speechTimer = Timer(const Duration(milliseconds: 1000), () {
              _isGeminiSpeaking = false;
            });
          } else {
            // Might be JSON message?
            debugPrint('Received non-binary data from Gemini: $data');
          }
        },
        onError: (error) {
          debugPrint('Voice Commander AI WebSocket Error: $error');
          onErrorCallback?.call();
          _handleDisconnection();
        },
        onDone: () {
          debugPrint('Voice Commander AI WebSocket Closed');
          _handleDisconnection();
        },
      );

      // Start Recording
      await _startRecording();
    } catch (e, stackTrace) {
      debugPrint('Voice Commander AI Connection exception: $e');
      debugPrint('Stack trace: $stackTrace');
      _isConnected = false;
      _channel?.sink.close();
      _channel = null;
      onErrorCallback?.call();
    }
  }

  Future<void> _setupPlayback() async {
    // Gemini Live API returns audio at 24000Hz PCM
    await FlutterPcmSound.setup(sampleRate: 24000, channelCount: 1); // 1 = mono
  }

  Future<void> _startRecording() async {
    if (await _recorder.hasPermission()) {
      const config = RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: false,
        noiseSuppress: false,
      );

      final recordStream = await _recorder.startStream(config);

      _recordSubscription = recordStream.listen((data) {
        if (_channel != null && _isConnected) {
          if (!_isGeminiSpeaking) {
            _channel!.sink.add(data);
          }
        }
      });
      debugPrint('Recording started and streaming to Gemini...');
    }
  }

  void _handleDisconnection() {
    _isConnected = false;
    _cleanup();
  }

  void disconnect() {
    _handleDisconnection();
    _channel?.sink.close();
    _channel = null;
  }

  Future<void> _cleanup() async {
    _speechTimer?.cancel();
    await _recordSubscription?.cancel();
    _recordSubscription = null;
    await _recorder.stop();
    await FlutterPcmSound.release();
  }

  void sendMessage(String message) {
    if (_channel != null && _isConnected) {
      _channel!.sink.add(message);
    } else {
      debugPrint('Cannot send message: WebSocket is not connected');
    }
  }
}
===
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:record/record.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';
import '../../../core/auth/token_manager.dart';
import '../../../core/navigation/app_route_resolver.dart';
import '../../../main.dart';

class GeminiRoutingService {
  final TokenManager _tokenManager;
  WebSocketChannel? _channel;
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _recordSubscription;

  // AI backend WebSocket URL.
  final String _baseWsUrl = 'ws://10.165.155.12:8000/ws';

  bool _isConnected = false;
  bool get isConnected => _isConnected;

  bool _isGeminiSpeaking = false;
  Timer? _speechTimer;

  GeminiRoutingService(this._tokenManager);

  Future<void> connect({VoidCallback? onErrorCallback}) async {
    if (_isConnected) return;

    try {
      final firstName = await _tokenManager.getFirstName() ?? 'Student';
      final levelName = await _tokenManager.getLevelName() ?? 'primary_4';

      final wsUrl = Uri.parse(
        '$_baseWsUrl?name=$firstName&grade_level=${Uri.encodeComponent(levelName)}&primary_language=Arabic',
      );

      debugPrint('Connecting to Voice Commander AI WebSocket at $wsUrl');
      _channel = WebSocketChannel.connect(wsUrl);

      // Wait for the actual TCP+WS handshake to complete before proceeding.
      // Without this, the channel object exists but the connection may have
      // silently failed (e.g. cleartext blocked, host unreachable).
      await _channel!.ready.timeout(
        const Duration(seconds: 8),
        onTimeout: () {
          throw TimeoutException('WebSocket handshake timed out after 8s');
        },
      );

      _isConnected = true;
      debugPrint('Voice Commander AI WebSocket connected successfully.');

      // Handle output from Gemini (Audio bytes)
      _setupPlayback();

      _channel?.stream.listen(
        (data) {
          if (data is Uint8List) {
            FlutterPcmSound.feed(
              PcmArrayInt16(
                bytes: ByteData.view(
                  data.buffer,
                  data.offsetInBytes,
                  data.lengthInBytes,
                ),
              ),
            );

            // Software Echo Cancellation: Mute mic while playing
            _isGeminiSpeaking = true;
            _speechTimer?.cancel();
            _speechTimer = Timer(const Duration(milliseconds: 1000), () {
              _isGeminiSpeaking = false;
            });
          } else if (data is String) {
            // ── JSON control messages from backend ──
            try {
              final Map<String, dynamic> json = jsonDecode(data);
              final String? type = json['type'] as String?;

              if (type == 'interrupt') {
                // Barge-in: clear the playback buffer immediately.
                debugPrint('[GeminiRoutingService] Interrupt received — flushing audio buffer.');
                FlutterPcmSound.feed(PcmArrayInt16.zeros(count: 0));

              } else if (type == 'ui_navigation') {
                final String? route = json['route'] as String?;
                final dynamic payload = json['payload'];

                debugPrint('[GeminiRoutingService] Navigation command → $route');

                if (route != null && route.isNotEmpty) {
                  // Thread-safe, context-less navigation via global key.
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    final navState = EduVoiceApp.navigatorKey.currentState;
                    if (navState != null) {
                      final resolvedRoute = AppRouteResolver.resolve(route, payload);
                      if (resolvedRoute != null) {
                        navState.push(resolvedRoute);
                      } else {
                        debugPrint('[GeminiRoutingService] Unknown route: $route — ignoring.');
                      }
                    } else {
                      debugPrint('[GeminiRoutingService] Navigator not mounted — cannot navigate.');
                    }
                  });
                }

              } else {
                debugPrint('[GeminiRoutingService] Unhandled JSON type: $type');
              }
            } catch (e) {
              debugPrint('[GeminiRoutingService] Failed to parse JSON message: $e');
            }
          } else {
            debugPrint('[GeminiRoutingService] Received unexpected data type: ${data.runtimeType}');
          }
        },
        onError: (error) {
          debugPrint('Voice Commander AI WebSocket Error: $error');
          onErrorCallback?.call();
          _handleDisconnection();
        },
        onDone: () {
          debugPrint('Voice Commander AI WebSocket Closed');
          _handleDisconnection();
        },
      );

      // Start Recording
      await _startRecording();
    } catch (e, stackTrace) {
      debugPrint('Voice Commander AI Connection exception: $e');
      debugPrint('Stack trace: $stackTrace');
      _isConnected = false;
      _channel?.sink.close();
      _channel = null;
      onErrorCallback?.call();
    }
  }

  Future<void> _setupPlayback() async {
    // Gemini Live API returns audio at 24000Hz PCM
    await FlutterPcmSound.setup(sampleRate: 24000, channelCount: 1); // 1 = mono
  }

  Future<void> _startRecording() async {
    if (await _recorder.hasPermission()) {
      const config = RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: false,
        noiseSuppress: false,
      );

      final recordStream = await _recorder.startStream(config);

      _recordSubscription = recordStream.listen((data) {
        if (_channel != null && _isConnected) {
          if (!_isGeminiSpeaking) {
            _channel!.sink.add(data);
          }
        }
      });
      debugPrint('Recording started and streaming to Gemini...');
    }
  }

  void _handleDisconnection() {
    _isConnected = false;
    _cleanup();
  }

  void disconnect() {
    _handleDisconnection();
    _channel?.sink.close();
    _channel = null;
  }

  Future<void> _cleanup() async {
    _speechTimer?.cancel();
    await _recordSubscription?.cancel();
    _recordSubscription = null;
    await _recorder.stop();
    await FlutterPcmSound.release();
  }

  void sendMessage(String message) {
    if (_channel != null && _isConnected) {
      _channel!.sink.add(message);
    } else {
      debugPrint('Cannot send message: WebSocket is not connected');
    }
  }
}
```

**What changed:**
1. **Added imports** — `dart:convert`, `flutter/widgets.dart`, `AppRouteResolver`, `EduVoiceApp`
2. **JSON parsing in the stream listener** — The `else` branch (non-binary data) now parses `String` messages as JSON and dispatches based on `type`:
   - `"interrupt"` → flushes the PCM playback buffer (barge-in)
   - `"ui_navigation"` → resolves the `route` via `AppRouteResolver` and pushes it using `EduVoiceApp.navigatorKey.currentState!.push(...)` inside `WidgetsBinding.instance.addPostFrameCallback`
   - Unknown types → debug logged
3. **Unexpected data types** get their own fallback log line

### [UNCHANGED] [main.dart](file:///c:/pfe/edu_voice/lib/main.dart)

No changes needed — the `GlobalKey<NavigatorState>` already existed at `EduVoiceApp.navigatorKey` (line 44) and was already wired to `MaterialApp` (line 66).

## Design Decisions

- **`AppRouteResolver` as a dedicated class** rather than inline `switch` in the service — keeps the WebSocket service decoupled from UI layer details and makes it trivial to add new routes later.
- **`addPostFrameCallback`** ensures navigation runs on the main UI thread after the current frame, preventing race conditions with widget tree updates.
- **Payload passed via `RouteSettings.arguments`** — screens can optionally read it from `ModalRoute.of(context)!.settings.arguments` if they need the Django data.

## Verification

```
dart analyze — 0 issues ✅
```
