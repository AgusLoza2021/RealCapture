@echo off
REM ============================================================================
REM  RealCapture - camera to rig, one command.
REM
REM  Double-click this file (or run it from a terminal) and sit in front of the
REM  camera: your face drives a real MPFB2 character in Blender.
REM
REM  What it starts:
REM    1. the camera pipeline in its own window (MediaPipe face blendshapes
REM       -> UDP 127.0.0.1:11111)
REM    2. Blender with the real generated character, bound through the addon,
REM       listening on that same port
REM
REM  Usage:
REM    camera-to-rig.cmd            uses camera 0
REM    camera-to-rig.cmd 1          uses camera 1
REM
REM  Close the Blender window to stop; this script then stops the pipeline.
REM
REM  NOTE: with nothing in front of the camera, MediaPipe detects no face and
REM  the backend sends no packets at all (by design). The Blender window will
REM  look frozen until a face appears - that is not a hang.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "CAMERA=%~1"
if "%CAMERA%"=="" set "CAMERA=0"

set "PORT=11111"
set "PY=backend\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "BLENDER=C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
if not exist "%BLENDER%" (
  echo ERROR: Blender not found at "%BLENDER%"
  echo Edit this file and point BLENDER at your Blender 4.5 executable.
  pause
  exit /b 2
)

set "CHARACTER=C:\Users\Lozita\AppData\Local\Temp\rc_mpfb\tmp\character.blend"
if not exist "%CHARACTER%" (
  echo ERROR: the MPFB2 character blend is missing:
  echo   "%CHARACTER%"
  echo Regenerate it before running this demo.
  pause
  exit /b 3
)

REM MPFB2 is installed in an isolated Blender config, not in the user's profile.
set "BLENDER_USER_CONFIG=C:\Users\Lozita\AppData\Local\Temp\rc_mpfb\env\config"
set "BLENDER_USER_EXTENSIONS=C:\Users\Lozita\AppData\Local\Temp\rc_mpfb\env\extensions"
set "BLENDER_USER_DATA=C:\Users\Lozita\AppData\Local\Temp\rc_mpfb\env\data"

echo === RealCapture: camera %CAMERA% -^> UDP 127.0.0.1:%PORT% -^> MPFB2 character ===
echo.
echo Starting the camera pipeline in its own window...
start "RealCapture camera pipeline" cmd /k ""%PY%" backend\run_capture.py --engine mediapipe --camera %CAMERA% --fps 30 --port %PORT%"

echo Waiting for the camera to open...
REM ping, not timeout: "timeout" can resolve to a non-Windows binary on a PATH
REM that also contains git-bash / MSYS tools.
ping -n 7 127.0.0.1 >nul 2>&1

echo Starting Blender. Sit in front of the camera.
"%BLENDER%" --factory-startup --python tools\blender_mpfb_live.py -- --port %PORT%

echo.
echo Blender closed. Stopping the camera pipeline...
taskkill /FI "WINDOWTITLE eq RealCapture camera pipeline*" /T /F >nul 2>&1
echo Done.
endlocal
