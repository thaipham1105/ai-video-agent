@echo off
REM Bo boc cho aiva-ui.ps1 — de tao shortcut Desktop bang double-click ma khong
REM phai doi ExecutionPolicy cua may.
REM
REM -NoProfile: khong nap profile PowerShell cua nguoi dung (nhanh hon, it bat ngo hon).
REM -ExecutionPolicy Bypass: chi ap dung cho DUNG tien trinh nay, khong doi cai dat may.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0aiva-ui.ps1"
