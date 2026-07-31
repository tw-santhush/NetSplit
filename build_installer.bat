@echo off
cd /d C:\projects\NetSplit
echo Building NetSplit V3.1.1 Installer...

echo Step 1: Installing Python dependencies...
call pip install -r requirements.txt
if errorlevel 1 exit /b %errorlevel%

echo Step 2: Packaging application with PyInstaller...
call pip install pyinstaller
if errorlevel 1 exit /b %errorlevel%
call pyinstaller --noconfirm NetSplit.spec
if errorlevel 1 exit /b %errorlevel%

echo Step 3: Building installer with Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
    if errorlevel 1 exit /b %errorlevel%
) else (
    echo Inno Setup not found. Skipping installer step.
    echo You can manually create an installer using the PyInstaller output in: dist\NetSplit.exe
)

echo Build complete!
if exist "dist\NetSplit Setup.exe" (
    echo Installer located at: C:\projects\NetSplit\dist\NetSplit Setup.exe
) else (
    echo Standalone executable located at: C:\projects\NetSplit\dist\NetSplit.exe
)
pause
