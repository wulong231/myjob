@echo off
setlocal
REM ============================================================
REM  Bili23 MediaSession Verification Script
REM  Purpose: verify whether the app's MediaSession is registered
REM  on the system (lockscreen / AOD / control-center controls).
REM  Usage:   check_media_session.bat [package_name]
REM  Default: com.bili23.android
REM ============================================================

set "PKG=com.bili23.android"
if not "%~1"=="" set "PKG=%~1"

echo [1/6] Checking adb...
where adb >nul 2>&1
if errorlevel 1 (
    REM Fall back to the bundled SDK adb when adb is not in PATH
    if exist "%~dp0sdk\platform-tools\adb.exe" set "PATH=%~dp0sdk\platform-tools;%PATH%"
)
where adb >nul 2>&1
if errorlevel 1 (
    echo   FAIL: adb not found. Install platform-tools or keep android\sdk\ in place.
    exit /b 1
)
echo   OK: adb available.

echo.
echo [2/6] Checking device connection...
set "CONNECTED="
for /f "usebackq delims=" %%a in (`adb devices`) do (
    echo %%a | findstr /v "List of devices attached" >nul && echo %%a | findstr /i "device" >nul && set "CONNECTED=1"
)
if not defined CONNECTED (
    echo   FAIL: no device/emulator connected. Run `adb devices`.
    exit /b 1
)
echo   OK: device connected.

echo.
echo [3/6] MediaSession registration (look for "BiliMusic")...
adb shell dumpsys media_session | findstr /i "bili"
if errorlevel 1 (
    echo   FAIL: MediaSession "BiliMusic" NOT found in the media_session list.
    echo         The system does not see the session yet - code-side issue.
    exit /b 1
)
echo   OK: MediaSession is registered on the system.

echo.
echo [4/6] Playback state (3=playing, 2=paused)...
adb shell dumpsys media_session | findstr /i "state="
echo   Note: lockscreen/AOD card only shows while actually playing.

echo.
echo [5/6] MusicPlaybackService foreground status...
adb shell dumpsys activity services %PKG% | findstr /i "MusicPlaybackService"
adb shell dumpsys activity services %PKG% | findstr /i "isForeground"
echo   Note: if not foreground, the service may have been killed by the system.

echo.
echo [6/6] Notification permission (Android 13+)...
adb shell dumpsys package %PKG% | findstr /i "POST_NOTIFICATIONS"
echo   Note: lockscreen media card attaches to the media notification.
echo         Must be allowed in system settings.

echo.
echo ============================================================
echo  DONE. If [3/6] shows the session but the lockscreen/AOD card
echo  still does not appear, the cause is on the ROM side:
echo    - vivo: enable "music/lockscreen display" in system settings
echo    - keep the song playing (card hides ~5min after pause)
echo    - whitelist the app for background operation
echo ============================================================
endlocal
