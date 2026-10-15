@echo off
chcp 65001 >nul
title Bili23 Build

setlocal enabledelayedexpansion

:: pip mirrors (China)
set MIRROR_ALIYUN=https://mirrors.aliyun.com/pypi/simple/
set MIRROR_TSINGHUA=https://pypi.tuna.tsinghua.edu.cn/simple
set MIRROR_PYPI=https://pypi.org/simple/

echo ========================================
echo      Bili23 - PyInstaller Build
echo ========================================
echo.

:: ---------- 1. Check Python ----------
echo [1/6] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo        Python %PY_VER%

:: ---------- 2. Clean venv ----------
echo [2/6] Creating fresh virtual environment...
set VENV_DIR=%~dp0venv
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo        Removing old venv...
    rmdir /s /q "%VENV_DIR%" 2>nul
)
echo        Creating venv...
python -m venv "%VENV_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment
    pause
    exit /b 1
)
echo        venv created

:: ---------- 3. Test network & pick mirror ----------
echo [3/6] Testing network connectivity...
"%VENV_DIR%\Scripts\python" -c "import urllib.request; urllib.request.urlopen('https://mirrors.aliyun.com/pypi/simple/', timeout=10)" >nul 2>&1
if %errorlevel% equ 0 (
    set PIP_MIRROR=%MIRROR_ALIYUN%
    echo        Using Aliyun mirror
) else (
    "%VENV_DIR%\Scripts\python" -c "import urllib.request; urllib.request.urlopen('https://pypi.tuna.tsinghua.edu.cn', timeout=10)" >nul 2>&1
    if %errorlevel% equ 0 (
        set PIP_MIRROR=%MIRROR_TSINGHUA%
        echo        Using Tsinghua mirror
    ) else (
        set PIP_MIRROR=%MIRROR_PYPI%
        echo        No mirror reachable, using direct PyPI
    )
)

:: set PIP_INDEX_URL to override global pip config (e.g. Tsinghua mirror)
set PIP_INDEX_URL=%PIP_MIRROR%

:: ---------- 4. Install runtime deps ----------
echo [4/6] Installing runtime dependencies...

:: PySide6 is ~200MB, needs a long timeout
"%VENV_DIR%\Scripts\pip" install PySide6 --timeout=600
if %errorlevel% equ 0 (
    echo        PySide6 installed
) else (
    echo [ERROR] PySide6 installation failed
    pause
    exit /b 1
)

"%VENV_DIR%\Scripts\pip" install PySide6-Fluent-Widgets httpx mutagen pynput cryptography qrcode ffmpeg-python pillow --timeout=120
if %errorlevel% equ 0 (
    echo        All dependencies installed
) else (
    echo [ERROR] Dependency installation failed
    pause
    exit /b 1
)

:: ---------- 5. Install PyInstaller ----------
echo [5/6] Installing PyInstaller...
"%VENV_DIR%\Scripts\pip" install pyinstaller --timeout=120
if %errorlevel% equ 0 (
    echo        PyInstaller installed
) else (
    echo [ERROR] PyInstaller installation failed
    pause
    exit /b 1
)

:: ---------- 5. Patch qfluentwidgets label setTextColor for light theme init ----------
echo [5/7] Patching label setTextColor for light theme init...
powershell -Command "$f = '%VENV_DIR%\Lib\site-packages\qfluentwidgets\components\widgets\label.py'; $c = Get-Content $f -Raw; if ($c -notmatch 'isDarkTheme') { $old = 'addStyleSheet(self, CustomStyleSheet(self))'; $new = 'addStyleSheet(self, CustomStyleSheet(self))' + [char]10 + [char]10 + '        # Force apply: resolves Theme.AUTO properly' + [char]10 + '        dark_theme = isDarkTheme()' + [char]10 + '        force_qss = dark_qss if dark_theme else light_qss' + [char]10 + "        self.setStyleSheet(self.styleSheet() + [char]10 + force_qss)"; $c = $c.Replace($old, $new); Set-Content $f -Value $c -Encoding UTF8; Write-Host 'patched' } else { Write-Host 'already patched' }"
if %errorlevel% equ 0 (
    echo        label.py patched
) else (
    echo [WARNING] label.py patch failed - labels may have contrast issues
)

:: ---------- 6. Check ffmpeg ----------
echo [6/7] Checking ffmpeg...
if not exist "%~dp0bin\ffmpeg.exe" (
    echo        ffmpeg.exe not found in bin\ - ffmpeg features will be unavailable
    echo        (audio conversion, video thumbnails, etc.)
)
if not exist "%~dp0bin" (
    mkdir "%~dp0bin" >nul 2>&1
)

:: ---------- 7. Build with PyInstaller ----------
echo.
echo        Building with PyInstaller (may take 3-5 minutes)...
echo.

cd /d "%~dp0"
"%VENV_DIR%\Scripts\pyinstaller" "%~dp0Bili23_onefile.spec" --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed - check error messages above
    pause
    exit /b 1
)

echo.
echo ========================================
echo     Build Complete!
echo ========================================
echo.
echo Output: dist\Bili23.exe
echo.
pause