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
REM    6  the camera pipeline could not be started: the launch returned no
REM       usable process record, so there is nothing owned and Blender was
REM       not started
REM    7  the recorded pipeline could not be confirmed stopped (identity check
REM       or termination failed) - close its window manually if it is open
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
REM    (there is no variable for the UDP port: it is fixed at 11111 so the
REM    addon always listens where the pipeline sends)
REM
REM  NOTE: with nothing in front of the camera, MediaPipe detects no face and
REM  the backend sends no packets at all (by design). The Blender window will
REM  look frozen until a face appears - that is not a hang.
REM
REM  SAFETY: the camera pipeline is started through Start-Process -PassThru,
REM  so this launcher holds the concrete PID of a process it created itself,
REM  and the post-Blender stop calls one shared routine that stops only that
REM  recorded PID and its descendants - never a window title or an image
REM  name. Live evidence: a window-title stop once matched the shared Windows
REM  Terminal host and killed unrelated terminal tabs. Before stopping, the
REM  routine re-validates the recorded PID's process identity (executable,
REM  recorded start time, and the exact launch command), so a recycled PID
REM  owned by another process is left alone, and it reports its outcome so
REM  this launcher never claims a stop that did not happen.
REM ============================================================================
setlocal
cd /d "%~dp0"

REM --- machine-specific overrides (optional, gitignored) ----------------------
REM Sourced BEFORE any default below is resolved. If the file is absent,
REM continue silently: that is the normal case, not a failure.
if exist "%~dp0local.cmd" call "%~dp0local.cmd"

REM --- the UDP port of the camera pipeline ----------------------------------
REM Defined HERE on purpose. An undefined %PORT% expands to nothing, so the
REM backend gets "--port" with no value, dies with "argument --port:
REM expected one argument", and Blender still opens and never receives a
REM packet: a broken run that looks like a working one with no face in view.
REM Fixed on purpose, so it always matches backend/run_capture.py and the
REM addon's own udp_port setting.
set "PORT=11111"

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

REM --- PID ownership -----------------------------------------------------------
REM Start-Process -PassThru returns the concrete PID of the console wrapper we
REM create here; recording it is what makes the post-Blender stop safe. No
REM window-title or image-name matching anywhere: those can match the shared
REM Windows Terminal host or unrelated processes.
REM
REM %PY% stays unquoted on purpose: it is a fixed relative path with no spaces,
REM and quoting it through cmd-inside-PowerShell would add fragile
REM nested-quote parsing for nothing.
set "RC_CAPTURE_ARGS=%PY% backend\run_capture.py --engine mediapipe --camera %CAMERA% --fps 30 --port %PORT%"
for /f "usebackq tokens=1,2" %%A in (`powershell -NoProfile -Command "$p = Start-Process -FilePath $env:ComSpec -ArgumentList ('/k', ('title RealCapture camera pipeline& ' + $env:RC_CAPTURE_ARGS)) -PassThru; if ($null -eq $p) { exit 1 }; $t = $null; try { $t = $p.StartTime.ToUniversalTime().Ticks } catch { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; exit 1 }; Write-Output ($p.Id.ToString() + ' ' + $t)"`) do (
  set "CAPTURE_PID=%%A"
  set "CAPTURE_PID_BORN=%%B"
)

REM Fail closed on a missing or malformed launch record: both values must be
REM plain decimal numbers before they are used anywhere - and Blender must
REM not start on top of a pipeline that was never owned.
if not defined CAPTURE_PID goto :launch_record_failed
if not defined CAPTURE_PID_BORN goto :launch_record_failed
echo %CAPTURE_PID%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto :launch_record_failed
echo %CAPTURE_PID_BORN%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto :launch_record_failed
goto :launch_record_ok

:launch_record_failed
REM Best-effort orphan mitigation: if the PID itself was captured, stop the
REM process we just created (within this same second, so PID reuse is not a
REM realistic concern here); without a valid record this cannot use the
REM start-time guard, so it is a narrow kill of our own child only.
echo %CAPTURE_PID%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if not errorlevel 1 powershell -NoProfile -Command "Stop-Process -Id $env:CAPTURE_PID -Force -ErrorAction SilentlyContinue"
echo ERROR: the camera pipeline launch record is missing or malformed, so
echo nothing can be owned or stopped safely, and Blender was NOT started. If
echo a capture window did open, close it manually.
endlocal
exit /b 6

:launch_record_ok
echo Camera pipeline running as PID %CAPTURE_PID% in its own window.

echo Waiting for the camera to open...
REM ping, not timeout: "timeout" can resolve to a non-Windows binary on a PATH
REM that also contains git-bash / MSYS tools.
ping -n 7 127.0.0.1 >nul 2>&1

echo Starting Blender. Sit in front of the camera.
"%BLENDER%" --factory-startup --python tools\blender_mpfb_live.py -- --port %PORT%

echo.
echo Blender closed. Stopping the camera pipeline...
call :stop_capture
if errorlevel 1 (
  echo ERROR: the recorded camera pipeline could not be confirmed stopped: the
  echo identity check or the termination failed. If its window is still open,
  echo close it manually.
  endlocal
  exit /b 7
)
echo Done.
endlocal
exit /b 0

:stop_capture
REM Stops ONLY the process recorded at launch, and its descendants. Guards,
REM in order:
REM   1. fail closed: without both recorded values this routine reports
REM      failure and stops nothing - an empty value must never reach a
REM      stop command;
REM   2. numeric guards: both recorded values must be plain decimal numbers
REM      before they are used anywhere;
REM   3. identity: the PID's process must still exist, must be cmd.exe at
REM      ComSpec, and its creation time must equal the recorded start time -
REM      this rejects a recycled PID even when the command line matches;
REM   4. exact capture command: the command line must still contain the
REM      exact RC_CAPTURE_ARGS launch command.
REM Only after all four does the child-first tree stop run; the root is
REM re-checked afterwards, and exit status 1 means the caller must NOT claim
REM the pipeline was stopped.
if not defined CAPTURE_PID exit /b 1
if not defined CAPTURE_PID_BORN exit /b 1
echo %CAPTURE_PID%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 exit /b 1
echo %CAPTURE_PID_BORN%| findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 exit /b 1
powershell -NoProfile -Command "$p = Get-Process -Id $env:CAPTURE_PID -ErrorAction SilentlyContinue; if (-not $p) { exit 0 }; $ok = $false; try { $born = $p.StartTime.ToUniversalTime().Ticks.ToString() } catch { $born = '' }; if ($born -eq $env:CAPTURE_PID_BORN -and $p.Path -and ($p.Path -ieq $env:ComSpec)) { $w = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:CAPTURE_PID); if ($w -and $w.CommandLine -and $w.CommandLine.IndexOf($env:RC_CAPTURE_ARGS, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { $ok = $true } }; if ($ok) { function Stop-Tree([int]$id) { Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $id) | ForEach-Object { Stop-Tree $_.ProcessId }; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }; Stop-Tree $env:CAPTURE_PID; Start-Sleep -Milliseconds 300; if (Get-Process -Id $env:CAPTURE_PID -ErrorAction SilentlyContinue) { exit 1 }; exit 0 }; exit 1"
goto :eof

:find_blender_under
REM %1 = a Program Files root. Pick the newest "Blender *" version folder that
REM actually contains blender.exe; dir /o-n lists newest-named folders first.
for /f "delims=" %%V in ('dir /b /ad /o-n "%~1\Blender Foundation\Blender *" 2^>nul') do if not defined BLENDER if exist "%~1\Blender Foundation\%%V\blender.exe" set "BLENDER=%~1\Blender Foundation\%%V\blender.exe"
goto :eof
