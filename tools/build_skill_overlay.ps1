$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$assets = Join-Path $taskRoot 'ams2season\assets'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe /optimize+ "/out:$assets\skill_overlay.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "$assets\skill_overlay.cs"
if ($LASTEXITCODE -ne 0) { throw 'Skill overlay compilation failed.' }
