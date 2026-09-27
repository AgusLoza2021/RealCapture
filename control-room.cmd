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
REM  Exit codes (one cause each):
REM    0  stopped normally
REM    3  the capture pipeline did not answer on its dashboard port in time
REM    4  the backend Python virtualenv is missing (backend\.venv)
REM    5  usage error (unknown or incomplete command-line arguments)
REM    6  the capture pipeline could not be started: the launch returned no
REM       usable process record, so there is nothing owned and nothing to stop
REM    7  the recorded pipeline could not be confirmed stopped (identity check
REM       or termination failed) - close its window manually if it is open
REM
REM  Portability: nothing machine-specific lives in this file. Put "set VAR=value"
REM  lines into local.cmd next to this launcher; it is sourced when present and
REM  its absence is normal. Blender is NOT started by this launcher, so it does
REM  not touch RC_BLENDER/RC_MPFB_ROOT: the window opens fine without Blender,
REM  and its light simply reads red with a reason until Blender joins.
REM
REM  NOTE: ping, not timeout: "timeout" can resolve to a non-Windows binary on
REM  a PATH that also contains git-bash / MSYS tools.
REM
REM  SAFETY: the capture pipeline is started through Start-Process -PassThru,
REM  so this launcher holds the concrete PID of a process it created itself,
REM  and every stop path calls one shared routine that stops only that
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

REM Machine-specific overrides (optional, gitignored), sourced before any
REM argument or default below is resolved. Absent file is the normal case.
if exist "%~dp0local.cmd" call "%~dp0local.cmd"

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
exit /b 5

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
exit /b 4

:have_python
echo === RealCapture control room: camera %CAMERA%, dashboard port %PORT% ===
echo.
echo Starting the capture pipeline in its own window...

REM --- PID ownership -----------------------------------------------------------
REM Start-Process -PassThru returns the concrete PID of the console wrapper we
REM create here; recording it is what makes every stop below safe. No
REM window-title or image-name matching anywhere: those can match the shared
REM Windows Terminal host or unrelated processes.
REM
REM %PY% stays unquoted on purpose: it is a fixed relative path with no spaces
REM (the repo layout is machine-independent), and quoting it through
REM cmd-inside-PowerShell would add fragile nested-quote parsing for nothing.
set "RC_CAPTURE_ARGS=%PY% backend\run_capture.py --engine mediapipe --camera %CAMERA% --fps 30 --dashboard %PORT%"
for /f "usebackq tokens=1,2" %%A in (`powershell -NoProfile -Command "$p = Start-Process -FilePath $env:ComSpec -ArgumentList ('/k', ('title RealCapture control room capture& ' + $env:RC_CAPTURE_ARGS)) -PassThru; if ($null -eq $p) { exit 1 }; $t = $null; try { $t = $p.StartTime.ToUniversalTime().Ticks } catch { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; exit 1 }; Write-Output ($p.Id.ToString() + ' ' + $t)"`) do (
  set "CAPTURE_PID=%%A"
  set "CAPTURE_PID_BORN=%%B"
)

REM Fail closed on a missing or malformed launch record: both values must be
REM plain decimal numbers before they are used anywhere.
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
echo ERROR: the capture pipeline launch record is missing or malformed, so
echo nothing can be owned or stopped safely. If a capture window did open,
echo close it manually.
endlocal
exit /b 6

:launch_record_ok
echo Capture pipeline running as PID %CAPTURE_PID% in its own window.

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
call :stop_capture
if errorlevel 1 (
  echo ERROR: the recorded pipeline could not be confirmed stopped: the identity
  echo check or the termination failed. If its window is still open, close it
  echo manually.
  endlocal
  exit /b 7
)
echo The capture pipeline was stopped (or had already exited); nothing is left running.
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
call :stop_capture
if errorlevel 1 (
  echo ERROR: the recorded pipeline could not be confirmed stopped: the identity
  echo check or the termination failed. If its window is still open, close it
  echo manually.
  endlocal
  exit /b 7
)
echo Capture stopped (or had already exited).
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
