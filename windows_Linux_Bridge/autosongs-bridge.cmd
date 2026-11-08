@echo off
rem AutoSongs bridge - one file for Windows.
rem
rem Double click it, or run it from a command prompt:
rem
rem     autosongs-bridge.cmd
rem
rem It prints a code. Type that code into AutoSongs on your phone, in
rem Settings - The bridge on another machine, and the two are paired.
rem
rem It needs python 3, and it puts yt-dlp in place for itself if it is not
rem there already.

setlocal enabledelayedexpansion
set "DIR=%USERPROFILE%\.autosongs"
set "BRIDGE=%DIR%\ytbridge.py"
set "LOG=%DIR%\bridge.log"
if not exist "%DIR%" mkdir "%DIR%"

rem A cookie jar next to this launcher is used for the downloads. YouTube
rem sometimes answers with "Sign in to confirm you're not a bot" instead
rem of the video, and a jar - the file a signed-in browser can export - is
rem what gets past it. The bridge looks for one on its own, but saying so
rem here means the jar the user put here is the one that is used.
set "HERE=%~dp0"
if not defined YTBRIDGE_COOKIES if exist "%HERE%cookies.txt" set "YTBRIDGE_COOKIES=%HERE%cookies.txt"
if defined YTBRIDGE_COOKIES set "YTBRIDGE_COOKIES=%YTBRIDGE_COOKIES%"

rem ---------------------------------------------------------------- python
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo The AutoSongs bridge needs python 3.
    echo.
    echo   winget install Python.Python.3
    echo.
    echo Then run this file again.
    pause
    exit /b 1
)

rem ---------------------------------------------------------------- yt-dlp
%PY% -c "import yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo Putting yt-dlp in place...
    %PY% -m pip install --user --upgrade yt-dlp >>"%LOG%" 2>&1
    %PY% -c "import yt_dlp" >nul 2>&1
    if errorlevel 1 (
        echo yt-dlp would not install. The details are in %LOG%
        pause
        exit /b 1
    )
)

rem ---------------------------------------------------------------- bridge
rem The bridge core is published only at https://autosongs.example; the old
rem throwaway host names are gone from this launcher so it can never pick
rem up an old published copy. And a fetched copy replaces
rem the local one only when it is strictly newer, so a newer bridge that
rem is already installed here is never downgraded - see :remote_is_newer.
set "GOT="
for %%H in (
    https://autosongs.example
) do (
    if not defined GOT call :try_host "%%H"
)
if defined GOT goto run_bridge
if exist "%BRIDGE%" (
    echo Using the copy of the bridge that is already here.
    goto run_bridge
)
rem Flat on purpose: cmd.exe drops the exit code of an EXIT /B that sits in
rem a nested block whose outer block continues afterwards.
echo The bridge could not be fetched, and there is no copy here.
echo Check the network and try again.
pause
exit /b 1

:run_bridge
%PY% "%BRIDGE%" --pair %*
pause
exit /b 0

rem ---------------------------------------------------------------- helpers
rem Fetch one host's copy. It becomes the bridge only when nothing is
rem installed yet, or when it is newer than what is installed; otherwise
rem the local copy is kept, which is good enough (GOT).
:try_host
del /Q "%BRIDGE%.new" >nul 2>&1
curl -fsSL --max-time 90 "%~1/ytbridge.py" -o "%BRIDGE%.new" >nul 2>&1
if not exist "%BRIDGE%.new" exit /b 0
findstr /C:"def make_server" "%BRIDGE%.new" >nul 2>&1
if errorlevel 1 (
    del /Q "%BRIDGE%.new" >nul 2>&1
    exit /b 0
)
call :remote_is_newer
if errorlevel 1 (
    echo Keeping the copy of the bridge that is already here.
    del /Q "%BRIDGE%.new" >nul 2>&1
    set "GOT=1"
    exit /b 0
)
move /Y "%BRIDGE%.new" "%BRIDGE%" >nul
set "GOT=1"
exit /b 0

rem Exit 0 when the fetched copy is strictly newer than the installed one,
rem or nothing is installed. Exit 1 otherwise: the fetched copy declares no
rem version, or the installed copy is as new as it gets. Never downgrade.
rem The line format is the bridge's own: BRIDGE_VERSION = "1.2.3"
:remote_is_newer
if not exist "%BRIDGE%" exit /b 0
set "R="
set "L="
for /f "tokens=3 delims= " %%V in ('findstr /b /c:"BRIDGE_VERSION" "%BRIDGE%.new"') do set "R=%%~V"
for /f "tokens=3 delims= " %%V in ('findstr /b /c:"BRIDGE_VERSION" "%BRIDGE%"') do set "L=%%~V"
if not defined R exit /b 1
if not defined L exit /b 0
for /f "tokens=1,2,3 delims=." %%A in ("%R%") do (set RT1=%%A&set RT2=%%B&set RT3=%%C)
for /f "tokens=1,2,3 delims=." %%A in ("%L%") do (set LT1=%%A&set LT2=%%B&set LT3=%%C)
if not defined RT2 set RT2=0
if not defined RT3 set RT3=0
if not defined LT2 set LT2=0
if not defined LT3 set LT3=0
if %RT1% gtr %LT1% exit /b 0
if %RT1% lss %LT1% exit /b 1
if %RT2% gtr %LT2% exit /b 0
if %RT2% lss %LT2% exit /b 1
if %RT3% gtr %LT3% exit /b 0
exit /b 1
