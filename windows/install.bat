@echo off
chcp 65001 >nul
title Bili23 安装程序
echo ========================================
echo      Bili23 - B站下载器 安装程序
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/3] Python 未检测到，尝试自动安装...
    :: 尝试 winget 安装 Python
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 无法自动安装 Python。
        echo 请手动从 https://www.python.org/downloads/ 下载安装 Python 3.8+
        echo 安装时请勾选 "Add Python to PATH"
        pause
        exit /b 1
    )
    echo Python 安装成功！请重新运行此脚本。
    pause
    exit /b 0
)
echo [1/3] Python 检测完毕

:: 检查 pip
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/3] pip 未检测到，尝试安装...
    python -m ensurepip --default-pip >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 无法安装 pip
        pause
        exit /b 1
    )
    python -m pip install --upgrade pip >nul 2>&1
)
echo [2/3] pip 检测完毕

:: 安装依赖
echo [3/3] 正在安装依赖包（首次安装可能需要几分钟）...
echo 安装 PySide6...
python -m pip install PySide6 -q
echo 安装 qfluentwidgets...
python -m pip install qfluentwidgets -q
echo 安装 mutagen...
python -m pip install mutagen -q
echo 安装 httpx...
python -m pip install httpx -q
echo 安装 cryptography...
python -m pip install cryptography -q
echo 安装 pynput...
python -m pip install pynput -q

echo.
echo ========================================
echo     安装完成！
echo ========================================
echo.
echo 运行程序：双击 run.bat 或运行 main.py
echo.
pause