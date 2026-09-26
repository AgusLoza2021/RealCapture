@echo off
REM ============================================================================
REM  RealCapture - control room, one command.
REM
REM  Double-click this file: it starts the capture pipeline and opens the
REM  dashboard window (your camera preview + the connection lights) in Edge's
REM  app mode, so it looks like a window and not a browser tab. Blender is NOT
REM  needed to open the window: if Blender is closed, its light simply reads
REM  amber or red inside the window.
REM
REM  Usage:
REM    control-room.cmd                 camera 0, dashboard port 8765
REM    control-room.cmd --port 9000     serve the window on another port
REM    control-room.cmd --camera 1      use another camera
REM    control-room.cmd --no-browser    start the capture, open nothing
REM                                     (so the launcher can be tested)
REM
REM  Pressing a key in this window stops the capture.
REM
REM  NOTE: ping, not timeout: "timeout" can resolve to a non-Windows binary on
REM  a PATH that also contains git-bash / MSYS tools.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PORT=8765"
set "CAMERA=0"
set "NOBROWSER="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--port" (
  if "%~2"=="" goto :bad_arg
  set "PORT=%~2"
  shift & shift
  goto :parse_args
)
if /i "%~1"=="--camera" (
  if "%~2"=="" goto :bad_arg
  set "CAMERA=%~2"
  shift & shift
  goto :parse_args
)
if /i "%~1"=="--no-browser" (
  set "NOBROWSER=1"
  shift
  goto :parse_args
)
:bad_arg
echo ERROR: unknown or incomplete argument "%~1"
echo Usage: control-room.cmd [--port N] [--camera N] [--no-browser]
endlocal
exit /b 2

:args_done
REM This launcher uses ONLY the project virtualenv. It deliberately does not
REM fall back to a system Python: a system interpreter without the capture
REM libraries would fail later, in a much more confusing way.
set "PY=backend\.venv\Scripts\python.exe"
if exist "%PY%" goto :have_python
echo ERROR: the Python virtualenv is missing:
echo   %CD%\%PY%
echo Create it once with:
echo   python -m venv backend\.venv
echo   backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
echo See backend\README.md for the exact dependency list.
pause
endlocal
exit /b 2

:have_python
echo === RealCapture control room: camera %CAMERA%, dashboard port %PORT% ===
echo.
echo Starting the capture pipeline in its own window...
start "RealCapture control room capture" cmd /k ""%PY%" backend\run_capture.py --engine mediapipe --camera %CAMERA% --fps 30 --dashboard %PORT%"

echo Waiting for the window to answer on http://127.0.0.1:%PORT%/ ...
set /a TRIES=0

:wait_probe
REM ping, not timeout: see the note at the top of this file.
ping -n 2 127.0.0.1 >nul 2>&1
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%PORT%/',timeout=2)" >nul 2>&1
if not errorlevel 1 goto :dashboard_up
set /a TRIES+=1
if %TRIES% lss 30 goto :wait_probe

echo.
echo ERROR: the capture pipeline did not answer on http://127.0.0.1:%PORT%/
echo within its wait bound, so no browser was opened. The most likely causes
echo are:
echo   - no camera is available, or another program is already holding it
echo   - antivirus or firewall software is blocking connections to 127.0.0.1
echo The capture pipeline's own output is in the "RealCapture control room
echo capture" window - read the error there. Pressing a key here stops the
echo capture pipeline and closes that window.
pause >nul
taskkill /FI "WINDOWTITLE eq RealCapture control room capture*" /T /F >nul 2>&1
echo The capture pipeline was stopped; nothing was left running.
endlocal
exit /b 3

:dashboard_up
if defined NOBROWSER (
  echo Dashboard is up on http://127.0.0.1:%PORT%/ - not opening a browser [--no-browser].
  goto :hold
)
REM App mode is the whole point of this launcher, and "where msedge" is NOT a
REM reliable test: a stock Windows install puts Edge under Program Files without
REM adding it to PATH, so the PATH check alone silently degrades to a normal
REM browser tab. Probe the install locations first, and say so when even those
REM are missing instead of quietly changing behaviour.
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%LocalAppData%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE="
if not defined EDGE for /f "delims=" %%E in ('where msedge 2^>nul') do if not defined EDGE set "EDGE=%%E"
if defined EDGE (
  start "" "%EDGE%" --app=http://127.0.0.1:%PORT%/
) else (
  echo NOTE: Microsoft Edge was not found, so the window opens as an ordinary
  echo browser tab rather than an app-style window. Everything inside it works
  echo the same; only the chrome around it differs.
  start "" http://127.0.0.1:%PORT%/
)

:hold
echo.
if defined NOBROWSER (
  echo The capture is running. Press any key here to stop it.
) else (
  echo The control room window is open. Press any key here to stop the capture.
)
pause >nul
taskkill /FI "WINDOWTITLE eq RealCapture control room capture*" /T /F >nul 2>&1
echo Capture stopped.
endlocal
