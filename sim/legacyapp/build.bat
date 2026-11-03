@echo off
rem Build with the csc.exe shipped in .NET Framework (no Visual Studio, no admin rights)
setlocal
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo csc.exe not found
  exit /b 1
)
cd /d "%~dp0"
if not exist bin mkdir bin
"%CSC%" /nologo /target:winexe /platform:x86 /out:bin\LegacyApp.exe ^
  /r:System.Windows.Forms.dll /r:System.Drawing.dll src\*.cs
exit /b %ERRORLEVEL%
