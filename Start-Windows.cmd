@echo off
setlocal
set PYTHONDONTWRITEBYTECODE=1
set PYTHONUTF8=1
if exist "%~dp0runtime\windows-x64\python.exe" (
  "%~dp0runtime\windows-x64\python.exe" "%~dp0app\library.py" %*
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0app\library.py" %*
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0app\library.py" %*
  goto done
)
echo Python 3.9+ is required. Install Python and try again.
pause
exit /b 1
:done
if errorlevel 1 pause
endlocal
