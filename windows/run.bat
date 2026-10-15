@echo off
chcp 65001 >nul
title Bili23 - B站下载器
:: 固定在脚本所在目录运行，保证 .bili23 配置/下载目录始终落在 windows\ 下
cd /d "%~dp0"
python "%~dp0main.py"
pause