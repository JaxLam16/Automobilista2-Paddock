# Compile the original metadata/number rules. No sound devices are used by this DLL.
param([string]$OutputDirectory, [string]$SourceDirectory)
$ErrorActionPreference='Stop'
$assetRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../ams2season/assets/crew_chief'))
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if ($SourceDirectory) {
    $assetRoot=[IO.Path]::GetFullPath($SourceDirectory)
    if (-not $assetRoot.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Sources must remain in workspace.' }
}
if (-not $OutputDirectory) { $OutputDirectory=$assetRoot }
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
if (-not $OutputDirectory.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must remain in this workspace.' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll')
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll')
$names=@('NumberReader.cs','NumberReaderEn.cs','TimeSpanWrapper.cs','CarNumber.cs','SoundSet.cs','SoundCacheSelection.cs','audio_metadata_host.cs')
$parse=[Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithLanguageVersion([Microsoft.CodeAnalysis.CSharp.LanguageVersion]::CSharp7_2)
$trees=[Microsoft.CodeAnalysis.SyntaxTree[]]@(foreach($name in $names) { [Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText((Join-Path $assetRoot $name)),$parse,$name) })
$framework=Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319'
$refs=[Microsoft.CodeAnalysis.MetadataReference[]]@(foreach($name in @('mscorlib.dll','System.dll','System.Core.dll','System.Web.Extensions.dll')) { [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile((Join-Path $framework $name)) })
$options=[Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new([Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary).WithOptimizationLevel([Microsoft.CodeAnalysis.OptimizationLevel]::Release).WithDeterministic($true)
$compilation=[Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('PaddockCrewAudio',$trees,$refs,$options)
$temporary=Join-Path $OutputDirectory ('audio_core.building.'+[Guid]::NewGuid().ToString('N'));$stream=[IO.File]::Create($temporary)
try { $result=$compilation.Emit($stream) } finally { $stream.Dispose() }
if (-not $result.Success) { $result.Diagnostics | Where-Object Severity -eq Error | ForEach-Object { Write-Output $_.ToString() };Remove-Item -LiteralPath $temporary;throw 'Crew Chief audio compilation failed.' }
$assemblyHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
$assemblyFile='audio_core.'+$assemblyHash+'.dll';$target=Join-Path $OutputDirectory $assemblyFile
# Loaded Framework DLLs are locked. Publish immutable versions so an active
# Paddock/recording can retain its loaded build without being interrupted.
if(Test-Path -LiteralPath $target) {
    if((Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant() -ne $assemblyHash) { throw 'Versioned audio assembly hash mismatch' }
    Remove-Item -LiteralPath $temporary
} else { Move-Item -LiteralPath $temporary -Destination $target }
$hashes=[ordered]@{};foreach($name in $names) { $hashes[$name]=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $assetRoot $name)).Hash.ToLowerInvariant() }
$receiptTemporary=Join-Path $OutputDirectory 'audio_core.build.json.tmp'
[ordered]@{version='4.19.5.4';language='C# 7.2';framework='.NET Framework 4.8';sources=$hashes;assembly_file=$assemblyFile;assembly_sha256=$assemblyHash} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptTemporary -Encoding utf8
Move-Item -LiteralPath $receiptTemporary -Destination (Join-Path $OutputDirectory 'audio_core.build.json') -Force
Write-Output $target
