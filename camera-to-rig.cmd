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
REM  Exit codes (one cause each):
REM    0  stopped normally
REM    2  Blender not found (set RC_BLENDER, or install Blender normally)
REM    3  the character .blend was not found (set RC_CHARACTER / RC_MPFB_ROOT)
REM    4  the backend Python virtualenv is missing (backend\.venv)
REM    5  usage error (bad command-line arguments)
REM
REM  Close the Blender window to stop; this script then stops the pipeline.
REM
REM  Portability: nothing machine-specific lives in this file. Override the
REM  defaults with the environment variables below (or put "set VAR=value"
REM  lines into local.cmd next to this launcher; it is sourced when present
REM  and its absence is normal):
REM    RC_MPFB_ROOT   root of the isolated Blender + MPFB2 environment
REM                   (default: %LOCALAPPDATA%\RealCapture\mpfb)
REM    RC_BLENDER     full path to blender.exe
REM                   (default: PATH, then the standard install folders,
REM                   newest version wins)
REM    RC_CHARACTER   full path to the character .blend
REM                   (default: %RC_MPFB_ROOT%\tmp\character.blend)
REM
REM  NOTE: with nothing in front of the camera, MediaPipe detects no face and
REM  the backend sends no packets at all (by design). The Blender window will
REM  look frozen until a face appears - that is not a hang.
REM ============================================================================
setlocal
cd /d "%~dp0"

REM --- machine-specific overrides (optional, gitignored) ----------------------
REM Sourced BEFORE any default below is resolved. If the file is absent,
REM continue silently: that is the normal case, not a failure.
if exist "%~dp0local.cmd" call "%~dp0local.cmd"

REM --- arguments ---------------------------------------------------------------
set "CAMERA=%~1"
if not "%~2"=="" goto :usage
if not defined CAMERA set "CAMERA=0"
REM The camera index must be a plain number; anything else is a usage error,
REM not a value to pass through and fail on later.
echo %CAMERA%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto :usage
goto :args_ok

:usage
if not "%~1"=="" echo ERROR: "%~1" is not a valid camera index.
if not "%~2"=="" echo ERROR: unexpected extra argument "%~2".
echo Usage: camera-to-rig.cmd [camera-index]
echo   camera-to-rig.cmd            uses camera 0
echo   camera-to-rig.cmd 1          uses camera 1
endlocal
exit /b 5

:args_ok
REM --- interpreter: the project virtualenv only, never a silent fallback ------
REM A fallback to a system Python would look like success and then fail later,
REM in a much more confusing way. Missing venv must say why and stop here.
set "PY=backend\.venv\Scripts\python.exe"
if exist "%PY%" goto :have_python
echo ERROR: the backend Python virtualenv is missing:
echo   %CD%\%PY%
echo This launcher never falls back to a system Python: a different interpreter
echo without the capture libraries would fail later, in a much more confusing
echo way. Create the virtualenv once - see backend\README.md for the exact
echo dependency list:
echo   python -m venv backend\.venv
echo   backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
pause
endlocal
exit /b 4

:have_python
REM --- Blender -----------------------------------------------------------------
REM RC_BLENDER wins when set. Otherwise: PATH first, then the standard install
REM folders under both Program Files roots (newest version folder wins).
set "BLENDER="
if defined RC_BLENDER set "BLENDER=%RC_BLENDER%"
if not defined BLENDER for /f "delims=" %%B in ('where blender 2^>nul') do if not defined BLENDER set "BLENDER=%%B"
if not defined BLENDER call :find_blender_under "%ProgramFiles%"
if not defined BLENDER call :find_blender_under "%ProgramFiles(x86)%"
if not defined BLENDER (
  echo ERROR: Blender was not found.
  echo Set RC_BLENDER to the full path of blender.exe - for example in
  echo local.cmd next to this launcher - or install Blender normally.
  pause
  endlocal
  exit /b 2
)
if not exist "%BLENDER%" (
  echo ERROR: RC_BLENDER points to a Blender executable that does not exist:
  echo   "%BLENDER%"
  echo Fix RC_BLENDER - for example in local.cmd - or unset it to let this
  echo launcher discover Blender on its own.
  pause
  endlocal
  exit /b 2
)

REM --- character ---------------------------------------------------------------
REM RC_CHARACTER wins when set; otherwise the RC_MPFB_ROOT default layout.
if not defined RC_MPFB_ROOT set "RC_MPFB_ROOT=%LOCALAPPDATA%\RealCapture\mpfb"
if defined RC_CHARACTER set "CHARACTER=%RC_CHARACTER%"
if not defined CHARACTER set "CHARACTER=%RC_MPFB_ROOT%\tmp\character.blend"
if not exist "%CHARACTER%" (
  echo ERROR: the MPFB2 character blend is missing:
  echo   "%CHARACTER%"
  echo Fix it with the variables that own this path:
  echo   - RC_CHARACTER: full path to your character .blend
  echo   - RC_MPFB_ROOT: root of the isolated MPFB2 environment; the launcher
  echo     looks for the character in RC_MPFB_ROOT\tmp\character.blend
  echo Create the character once in Blender with the MPFB2 add-on - see README.md.
  pause
  endlocal
  exit /b 3
)

REM MPFB2 is installed in an isolated Blender config, not in the user's profile.
REM All three are derived from RC_MPFB_ROOT, nothing else.
set "BLENDER_USER_CONFIG=%RC_MPFB_ROOT%\env\config"
set "BLENDER_USER_EXTENSIONS=%RC_MPFB_ROOT%\env\extensions"
set "BLENDER_USER_DATA=%RC_MPFB_ROOT%\env\data"

echo === RealCapture: camera %CAMERA% -^> UDP 127.0.0.1:%PORT% ===
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
exit /b 0

:find_blender_under
REM %1 = a Program Files root. Pick the newest "Blender *" version folder that
REM actually contains blender.exe; dir /o-n lists newest-named folders first.
for /f "delims=" %%V in ('dir /b /ad /o-n "%~1\Blender Foundation\Blender *" 2^>nul') do if not defined BLENDER if exist "%~1\Blender Foundation\%%V\blender.exe" set "BLENDER=%~1\Blender Foundation\%%V\blender.exe"
goto :eof
