param([string]$Defaults, [string]$Sounds)
$ErrorActionPreference = 'Stop'
function FileSha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}
# Source and assembly hashes prevent a stale private build from running silently.
$receipt = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'events_core.build.json') -Raw | ConvertFrom-Json
foreach ($entry in $receipt.sources.PSObject.Properties) {
    $actual = FileSha256 (Join-Path $PSScriptRoot $entry.Name)
    if ($actual -ne $entry.Value) { throw ('Rebuild Crew Chief events: source changed: ' + $entry.Name) }
}
$assembly = Join-Path $PSScriptRoot 'events_core.dll'
if ((FileSha256 $assembly) -ne $receipt.assembly_sha256) {
    throw 'Crew Chief event assembly hash mismatch. Rebuild the private event host.'
}
Add-Type -AssemblyName System.Web.Extensions
Add-Type -Path $assembly
[PaddockEventsHost]::Run($Defaults, $Sounds)
