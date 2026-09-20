@echo off
cd /d "%~dp0.."
title Codex x Claude live (web)
python ".pair\live.py" --port 8760
