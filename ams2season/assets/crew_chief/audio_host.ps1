param([string]$Defaults,[string]$Sounds)
$ErrorActionPreference='Stop'
function FileSha256([string]$Path) {
    $sha=[Security.Cryptography.SHA256]::Create();$stream=[IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose();$sha.Dispose() }
}
$receipt=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'audio_core.build.json') -Raw | ConvertFrom-Json
foreach($entry in $receipt.sources.PSObject.Properties) {
    if ((FileSha256 (Join-Path $PSScriptRoot $entry.Name)) -ne $entry.Value) { throw ('Rebuild Crew Chief audio: source changed: '+$entry.Name) }
}
$assemblyFile=if($receipt.assembly_file){[string]$receipt.assembly_file}else{'audio_core.dll'}
if($assemblyFile -notmatch '^audio_core(?:\.[0-9a-f]{64})?\.dll$') { throw 'Invalid audio assembly filename.' }
$assembly=Join-Path $PSScriptRoot $assemblyFile
if ((FileSha256 $assembly) -ne $receipt.assembly_sha256) { throw 'Crew Chief audio assembly hash mismatch.' }
Add-Type -AssemblyName System.Web.Extensions
Add-Type -Path $assembly
[PaddockAudioHost]::Run($Defaults,$Sounds)
