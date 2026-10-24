# TerminalVector

TerminalVector is a broadcast-control demo for two aircraft video scenarios. Aircraft telemetry and audience activity are simulated. It does not connect to live aircraft telemetry or a streaming service.

## Supported platform and requirements

- Apple silicon Mac (arm64)
- macOS 27.0 or later. The bundled native viewer is built with a macOS 27.0 minimum deployment target.
- Docker Desktop with Docker Compose, running and able to build `linux/arm64` images.
- Internet access on first launch to download the Docker base image. Internet access during the demo is also needed for the two Catbox-hosted videos and Google Fonts. The videos are not bundled because of their size and distribution constraints.

Chrome, host Python, and Swift/Xcode are not needed. The control room and program preview use the bundled native viewer and macOS WebKit. Docker runs the Python backend and automated director.

The bundled viewer was built on Apple silicon. A clean-machine launch from a downloaded ZIP, including macOS security behavior, has not yet been verified. If macOS blocks the viewer, record the exact message and stop; do not bypass the warning. A signed and notarized viewer or a clean-ZIP test may be needed for dependable distribution.

## Run the demo

From the project folder, run:

```bash
./start.sh
```

The launcher starts Docker Desktop if needed, builds and starts the backend and automated director, waits for the backend health endpoint, then opens the control room at the lower left and the OBS program preview at the upper right. Closing both windows ends the demo and removes the Compose services. Press Ctrl-C to stop it manually.

The windows keep the requested fixed sizes and positions. The current layout needs approximately **1665 × 994 logical points** of desktop area to show both windows without overlap or clipping. The arrangement was designed for the 1680 × 1050 logical-point display used for the reference screenshot. On a smaller effective desktop, use a larger display or increase the display resolution before launching; the launcher does not resize the windows.

For a headless run:

```bash
HEADLESS=1 ./start.sh
```

The backend API is exposed on port `8080` while the demo runs. Do not treat a successful `/health` response as proof that the videos loaded: verify that moving video is visible in the OBS preview.

## AI operator contract

Default behavior is presentation mode: start the demo, verify it using the checklist below, and leave it running for the team unless a person asks you to stop it. Allow about six minutes of unattended playback so the director can show both scenarios and the simulated audience events. Then test manual control and verify that automation resumes. Do not shut down the demo merely because the checklist is complete.

If the task explicitly requests an acceptance run rather than a presentation, perform the same checks and stop the demo afterward with Ctrl-C or by closing both windows. The launcher should then remove its Docker services.

## Success checklist

Confirm each item in the visible program preview and control room; backend health alone is insufficient.

- Both control room and program preview open in separate windows, fully visible and in the intended arrangement.
- Both Air Canada and Lufthansa videos show moving frames, and the program transitions between scenarios without becoming stuck on one clip.
- The aircraft tag and lower-third flight identity match the active scenario. Lufthansa telemetry progresses through its approach and rollout values.
- The **program-time** display starts at `01:34:23` for Air Canada and `04:05:12` for Lufthansa, counts upward, and resets to the correct sample time on a scenario change. This is separate from the lower-third **local-time** clock.
- Logo, lower-third information, and time controls independently show and hide their matching output elements. The aircraft-tag control shows and hides the tracking tag.
- Automated actions show simulated click feedback; chat, SuperChat, donation, and subscription events appear in the appropriate control-room and program areas.
- Clicking a window pauses automation for 10 seconds. A second interaction renews the override. After 10 seconds without interaction, the automated show resumes.
- Hiding a lower-third element removes its visual output cleanly, including its shadow.

If a video does not show moving frames, report it as a video/network failure even if the backend and fallback scene are visible.

## Troubleshooting and cleanup

- **Docker is unavailable:** Start Docker Desktop, wait for its engine to finish starting, and run `./start.sh` again.
- **Port 8080 is already in use:** Stop the process using it, then retry. On macOS, inspect the listener with `lsof -nP -iTCP:8080 -sTCP:LISTEN`. The launcher does not take over another service on that port.
- **Backend does not become ready or Compose fails:** The launcher prints container status and recent service logs before cleanup and saves them to `.terminalvector-failure.log`. Check that file before retrying. The first build needs network access to fetch the ARM64 base image.
- **Video is missing while the app otherwise opens:** Check internet access to the Catbox video host. A fallback background and a healthy backend do not mean video playback succeeded.
- **A window is partly off-screen:** Confirm the effective desktop meets the minimum above, then close both windows and relaunch.
- **Stop leftover services manually:** From the project folder, run `docker compose down --remove-orphans`.

The design document is maintained separately.

## Project files

- `app.py` — Python HTTP backend, state API, controller, overlay, and simulated program window.
- `auto_demo.py` — automated director that sends demo actions to the backend.
- `Dockerfile` and `docker-compose.yml` — ARM64 backend and director services.
- `start.sh` — one-command launcher and cleanup wrapper.
- `TerminalVectorViewer` — bundled Apple silicon macOS viewer using the system WebKit framework.
- `NativeViewer.swift` — viewer source for maintainers; building it is not part of the normal run path.
