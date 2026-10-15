#!/usr/bin/env bash
# Bili23 - PyInstaller build script (Linux)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# pip mirrors (China)
MIRROR_ALIYUN="https://mirrors.aliyun.com/pypi/simple/"
MIRROR_TSINGHUA="https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_PYPI="https://pypi.org/simple/"

echo "========================================"
echo "      Bili23 - PyInstaller Build"
echo "========================================"
echo

# ---------- 1. Check Python ----------
echo "[1/7] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python3 not found. Please install Python 3.8+"
    echo "        Debian/Ubuntu: sudo apt install python3 python3-venv"
    exit 1
fi
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo "       Python $PY_VER"

# ---------- 2. Check Linux kernel headers (needed to build evdev for pynput) ----------
echo "[2/7] Checking Linux kernel headers (for evdev)..."
if [ -f "/usr/include/linux/input.h" ]; then
    echo "       linux/input.h found"
else
    echo "       [WARNING] Linux kernel headers not found - pynput's evdev"
    echo "       dependency will fail to build from source."
    echo "       Install them first, then rerun this script:"
    if command -v apt-get >/dev/null 2>&1; then
        echo "         sudo apt-get install linux-headers-\$(uname -r)"
    elif command -v dnf >/dev/null 2>&1; then
        echo "         sudo dnf install kernel-headers-\$(uname -r)"
    elif command -v pacman >/dev/null 2>&1; then
        echo "         sudo pacman -S linux-api-headers"
    elif command -v zypper >/dev/null 2>&1; then
        echo "         sudo zypper install kernel-headers"
    elif command -v apk >/dev/null 2>&1; then
        echo "         sudo apk add linux-headers"
    else
        echo "         install the kernel header package for your distribution"
    fi
    echo "       Or skip compilation with prebuilt wheels: pip install evdev-binary"
    echo
fi

# ---------- 2b. Check Qt xcb platform libraries (GUI needs these on Linux) ----------
echo "       Checking Qt xcb platform libraries..."
MISSING_LIBS=""
for lib in libxcb-icccm.so.4 libxcb-keysyms.so.1 libxcb-image.so.0 libxcb-shape.so.0 libxcb-render-util.so.0 libxkbcommon-x11.so.0; do
    if ! ldconfig -p 2>/dev/null | grep -q "$lib"; then
        MISSING_LIBS="$MISSING_LIBS $lib"
    fi
done
if [ -n "$MISSING_LIBS" ]; then
    echo "       [WARNING] Qt xcb libraries missing - the GUI will fail to start."
    echo "       Install them with:"
    echo "         sudo apt install libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-shape0 libxcb-render-util0 libxkbcommon-x11-0"
fi

# ---------- 3. Clean venv ----------
echo "[3/7] Creating fresh virtual environment..."
VENV_DIR="$SCRIPT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    echo "       Removing old venv..."
    rm -rf "$VENV_DIR"
fi
echo "       Creating venv..."
if ! python3 -m venv "$VENV_DIR"; then
    echo "[ERROR] Failed to create virtual environment"
    exit 1
fi
echo "       venv created"

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ---------- 3. Test network & pick mirror ----------
echo "[4/7] Testing network connectivity..."
PIP_MIRROR="$MIRROR_PYPI"
if "$PY" -c "import urllib.request; urllib.request.urlopen('https://mirrors.aliyun.com/pypi/simple/', timeout=10)" >/dev/null 2>&1; then
    PIP_MIRROR="$MIRROR_ALIYUN"
    echo "       Using Aliyun mirror"
elif "$PY" -c "import urllib.request; urllib.request.urlopen('https://pypi.tuna.tsinghua.edu.cn', timeout=10)" >/dev/null 2>&1; then
    PIP_MIRROR="$MIRROR_TSINGHUA"
    echo "       Using Tsinghua mirror"
else
    echo "       No mirror reachable, using direct PyPI"
fi
export PIP_INDEX_URL="$PIP_MIRROR"

# ---------- 4. Install runtime deps ----------
echo "[5/7] Installing runtime dependencies..."

# PySide6 is ~200MB, needs a long timeout
if ! "$PIP" install PySide6 --timeout=600; then
    echo "[ERROR] PySide6 installation failed"
    exit 1
fi
echo "       PySide6 installed"

if ! "$PIP" install PySide6-Fluent-Widgets httpx mutagen cryptography qrcode ffmpeg-python pillow --timeout=120; then
    echo "[ERROR] Dependency installation failed"
    exit 1
fi

# pynput depends on evdev, which needs Linux kernel headers to compile.
# If headers are missing, install pynput itself without evdev directly:
# the app then falls back to in-app shortcuts (global hotkeys disabled).
if [ -f "/usr/include/linux/input.h" ]; then
    if ! "$PIP" install pynput --timeout=120; then
        echo "       [WARNING] pynput install failed - installing without evdev..."
        "$PIP" install pynput --no-deps --timeout=120 >/dev/null 2>&1 || true
        echo "       [WARNING] Global hotkeys unavailable; the app will use in-app shortcuts only."
    fi
else
    echo "       Kernel headers missing - skipping evdev build, installing pynput only..."
    "$PIP" install pynput --no-deps --timeout=120 >/dev/null 2>&1 || true
    echo "       [WARNING] Global hotkeys unavailable; the app will use in-app shortcuts only."
    echo "       To enable them later: install kernel headers, then: venv/bin/pip install pynput"
fi
echo "       All dependencies installed"

# ---------- 5. Install PyInstaller ----------
echo "[6/7] Installing PyInstaller..."
if ! "$PIP" install pyinstaller --timeout=120; then
    echo "[ERROR] PyInstaller installation failed"
    exit 1
fi
echo "       PyInstaller installed"

# ---------- 5b. Patch qfluentwidgets label setTextColor for light theme init ----------
echo "       Patching label setTextColor for light theme init..."
"$PY" - <<'PYEOF'
import os
import sysconfig

base = sysconfig.get_paths()["purelib"]
target = os.path.join(base, "qfluentwidgets", "components", "widgets", "label.py")

if not os.path.exists(target):
    print("       [WARNING] label.py not found - patch skipped")
else:
    with open(target, "r", encoding="utf-8") as f:
        c = f.read()
    if "Force apply" in c:
        print("       label.py already patched")
    else:
        old = "        addStyleSheet(self, CustomStyleSheet(self))"
        new = (
            old
            + "\n"
            + "\n"
            + "        # Force apply: isDarkTheme() properly resolves Theme.AUTO, unlike CustomStyleSheet.content()\n"
            + "        # which doesn't handle Theme.AUTO and always returns the dark stylesheet in that case.\n"
            + "        # This ensures the correct color is visible immediately during __init__.\n"
            + "        dark_theme = isDarkTheme()  # isDarkTheme() resolves AUTO to False (light)\n"
            + "        force_qss = dark_qss if dark_theme else light_qss\n"
            + "        self.setStyleSheet(self.styleSheet() + '\\n' + force_qss)"
        )
        if old in c:
            c = c.replace(old, new, 1)
            with open(target, "w", encoding="utf-8") as f:
                f.write(c)
            print("       label.py patched")
        else:
            print("       [WARNING] anchor not found in label.py - patch skipped")
PYEOF

# ---------- 6. Check ffmpeg ----------
echo "[7/7] Checking ffmpeg..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "       ffmpeg not found in PATH - ffmpeg features will be unavailable"
    echo "       (audio conversion, video thumbnails, etc.)"
    echo "       Install it via your package manager, e.g.:"
    echo "         Debian/Ubuntu: sudo apt install ffmpeg"
    echo "         Arch:          sudo pacman -S ffmpeg"
    echo "         Fedora:        sudo dnf install ffmpeg"
fi

# ---------- 7. Build with PyInstaller ----------
echo
echo "       Building with PyInstaller (may take 3-5 minutes)..."
echo

if ! "$VENV_DIR/bin/pyinstaller" "$SCRIPT_DIR/Bili23.spec" --noconfirm; then
    echo
    echo "[ERROR] Build failed - check error messages above"
    exit 1
fi

echo
echo "========================================"
echo "     Build Complete!"
echo "========================================"
echo
echo "Output: dist/Bili23"
echo
