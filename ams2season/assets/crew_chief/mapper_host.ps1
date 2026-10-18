param([string]$Defaults,[string]$Sounds,[string]$CrewChiefDirectory='C:/Program Files (x86)/Britton IT Ltd/CrewChiefV4')
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$settings=Get-Content -LiteralPath $Defaults -Raw | ConvertFrom-Json
if($settings.__paddock_installation) { $CrewChiefDirectory=$settings.__paddock_installation }
function FileSha256([string]$Path) {
    $sha=[Security.Cryptography.SHA256]::Create();$stream=[IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose();$sha.Dispose() }
}
$receipt=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'mapper_core.build.json') -Raw | ConvertFrom-Json
foreach($entry in $receipt.sources.PSObject.Properties) {
    if((FileSha256 (Join-Path $PSScriptRoot $entry.Name)) -ne $entry.Value) {throw ('Rebuild mapper: source changed: '+$entry.Name)}
}
foreach($entry in $receipt.metadata.PSObject.Properties) {
    if((FileSha256 (Join-Path $PSScriptRoot $entry.Name)) -ne $entry.Value) {throw ('Rebuild mapper: metadata changed: '+$entry.Name)}
}
$assemblyFile=if($receipt.assembly_file){[string]$receipt.assembly_file}else{'mapper_core.dll'}
if($assemblyFile -notmatch '^mapper_core(?:\.[0-9a-f]{64})?\.dll$') { throw 'Invalid mapper assembly filename.' }
$assembly=Join-Path $PSScriptRoot $assemblyFile
if((FileSha256 $assembly) -ne $receipt.assembly_sha256) {throw 'Mapper assembly hash mismatch'}
foreach($entry in $receipt.dependencies.PSObject.Properties) {
    $dependency=Join-Path $CrewChiefDirectory $entry.Name
    if((FileSha256 $dependency) -ne $entry.Value) {throw ('Mapper dependency hash mismatch: '+$entry.Name)}
    Add-Type -Path $dependency
}
Add-Type -Path $assembly
[PaddockMapperHost]::Run($Defaults,$Sounds,$CrewChiefDirectory)
