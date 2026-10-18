param([string]$Defaults, [string]$Sounds)
$ErrorActionPreference = 'Stop'
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'NoisyCartesianCoordinateSpotter.cs'))
# The only substitution in upstream code: deterministic, past-only telemetry time.
$source = $source.Replace('DateTime.UtcNow', 'PaddockClock.UtcNow')
$adapter = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'spotter_host.cs'))
$adapter = [regex]::Replace($adapter, '(?m)^using [^;]+;\r?\n', '')
$imports = 'using System.Collections; using System.Globalization; using System.Web.Script.Serialization;'
Add-Type -TypeDefinition ($imports + "`n" + $source + "`n" + $adapter) -ReferencedAssemblies 'System.Core','System.Web.Extensions' -WarningAction SilentlyContinue
[PaddockSpotterHost]::Run($Defaults, $Sounds)
