param([string]$Defaults, [string]$Sounds)
$ErrorActionPreference = 'Stop'
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'EngineMonitor.cs'))
# Windows Framework's compiler lacks interpolated strings. Diagnostic logging only.
$source = $source.Replace('Log.Commentary($"No data for {this.GetType().Name}");', 'Log.Commentary("No engine data");')
$adapter = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'engine_host.cs'))
$adapter = [regex]::Replace($adapter, '(?m)^using [^;]+;\r?\n', '')
$imports = 'using System.IO; using System.Collections; using System.Globalization; using System.Web.Script.Serialization;'
Add-Type -TypeDefinition ($imports + "`n" + $source + "`n" + $adapter) -ReferencedAssemblies 'System.Core','System.Web.Extensions' -WarningAction SilentlyContinue
[PaddockEngineHost]::Run($Sounds)
