# Build original C# 7.2 events for the .NET Framework runtime without touching CC.
# Run with PowerShell 7 (its bundled Roslyn compiler); the result runs in WinPS 5.
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$assetRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../ams2season/assets/crew_chief'))
if (-not $OutputDirectory) { $OutputDirectory = $assetRoot }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $OutputDirectory.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must remain in this workspace.'
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll')
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll')
$sourceNames = @('Penalties.cs', 'FlagsMonitor.cs', 'penalty_data.cs', 'flag_data.cs', 'events_host.cs', 'flags_adapter.cs')
$parseOptions = [Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithLanguageVersion(
    [Microsoft.CodeAnalysis.CSharp.LanguageVersion]::CSharp7_2)
$trees = [Microsoft.CodeAnalysis.SyntaxTree[]]@(
    foreach ($name in $sourceNames) {
        [Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText(
            [IO.File]::ReadAllText((Join-Path $assetRoot $name)), $parseOptions, $name)
    }
)
$framework = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319'
$references = [Microsoft.CodeAnalysis.MetadataReference[]]@(
    foreach ($name in @('mscorlib.dll','System.dll','System.Core.dll','System.Web.Extensions.dll')) {
        [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile((Join-Path $framework $name))
    }
)
$options = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new(
    [Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary).WithOptimizationLevel(
    [Microsoft.CodeAnalysis.OptimizationLevel]::Release).WithDeterministic($true)
$compilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('PaddockCrewEvents', $trees, $references, $options)
$target = Join-Path $OutputDirectory 'events_core.dll'
$temporary = $target + '.building'
$stream = [IO.File]::Create($temporary)
try { $result = $compilation.Emit($stream) } finally { $stream.Dispose() }
if (-not $result.Success) {
    $result.Diagnostics | Where-Object Severity -eq Error | ForEach-Object { Write-Output $_.ToString() }
    Remove-Item -LiteralPath $temporary
    throw 'Crew Chief event compilation failed.'
}
Move-Item -LiteralPath $temporary -Destination $target -Force
$hashes = [ordered]@{}
foreach ($name in $sourceNames) { $hashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $assetRoot $name)).Hash.ToLowerInvariant() }
[ordered]@{version='4.19.5.4'; language='C# 7.2'; framework='.NET Framework 4.8';
    compiler=[Microsoft.CodeAnalysis.CSharp.CSharpCompilation].Assembly.GetName().Version.ToString();
    sources=$hashes; assembly_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'events_core.build.json') -Encoding utf8
Write-Output $target
