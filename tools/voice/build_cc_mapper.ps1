# Run in bundled modern pwsh; compile original C# 7.2 for hidden WinPS 5.
param([string]$OutputDirectory, [string]$CrewChiefDirectory='C:/Program Files (x86)/Britton IT Ltd/CrewChiefV4', [string]$SourceDirectory, [string[]]$AdditionalSources=@())
$ErrorActionPreference='Stop'
$assetRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../ams2season/assets/crew_chief'))
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if ($SourceDirectory) {
    $assetRoot=[IO.Path]::GetFullPath($SourceDirectory)
    if (-not $assetRoot.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Sources must remain in workspace' }
}
if (-not $OutputDirectory) { $OutputDirectory=$assetRoot }
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
if (-not $OutputDirectory.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Output must remain in workspace' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll')
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll')
$sourceNames=@('GameStateData.cs','AMS2GameStateMapper.cs','GameStateMapper.cs','CarData.cs','TrackData.cs','GlobalBehaviourSettings.cs','Game.cs','GameDefinition.cs','GameDefinitionTable.cs','ams2_enums.cs','CommonDataContainers.cs','AdditionalDataProvider.cs','DriverNameHelper.cs','ams2_structs.cs','mapper_extensions.cs','mapper_host.cs','ConditionsMonitor.cs','AbstractEvent.cs','QueuedMessage.cs','SoundMetadata.cs','core_message_utils.cs','core_commands.cs','core_events.cs','NumberReader.cs','NumberReaderEn.cs','TimeSpanWrapper.cs','CarNumber.cs')
$sourceNames += @('EngineMonitor.cs','DamageReporting.cs','PearlsOfWisdom.cs','queue_original.cs','queue_moderator.cs','queue_host.cs')
$sourceNames += @('Fuel.cs','Fuel_legacy.cs','Fuel.TopicWindow.cs','RaceTime.cs','fuel_dependencies.cs','fuel_host.cs')
$sourceNames += @('PitStops.cs','pit_dependencies.cs','pit_host.cs')
$sourceNames += @('Position.cs','position_host.cs')
$sourceNames += @('LapCounter.cs','lapcounter_dependencies.cs','lapcounter_host.cs')
$sourceNames += @('Timings.cs','Timings_legacy.cs','OpponentMessages.cs','timing_dependencies.cs','timing_host.cs')
$sourceNames += @('TyreMonitor.cs','TyrePerformanceContainer.cs','tyre_estimator.cs','tyre_host.cs','tyre_dependencies.cs')
$sourceNames += @('LapTimes.cs','LapTimes_legacy.cs','laptimes_host.cs')
$sourceNames += @('mapper_startup.cs')
$sourceNames += @('SessionEndMessages.cs','session_end_host.cs')
$sourceNames += $AdditionalSources
$parse=[Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithLanguageVersion([Microsoft.CodeAnalysis.CSharp.LanguageVersion]::CSharp7_2)
$trees=[Microsoft.CodeAnalysis.SyntaxTree[]]@(foreach($name in $sourceNames){[Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText((Join-Path $assetRoot $name)),$parse,$name)})
$framework=Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319'
$references=[Microsoft.CodeAnalysis.MetadataReference[]]@(
    foreach($name in @('mscorlib.dll','System.dll','System.Core.dll','System.Web.Extensions.dll','System.Windows.Forms.dll','System.Drawing.dll','System.ValueTuple.dll')) {
        $refPath=Join-Path $framework $name
        if(Test-Path -LiteralPath $refPath){ [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($refPath) }
    }
    foreach($name in @('Newtonsoft.Json.dll','FuzzySharp.dll','Phonix.dll','MathNet.Numerics.dll')) { [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile((Join-Path $CrewChiefDirectory $name)) }
    [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile((Join-Path $env:SystemRoot 'Microsoft.NET/assembly/GAC_MSIL/System.Runtime/v4.0_4.0.0.0__b03f5f7f11d50a3a/System.Runtime.dll'))
)
$options=[Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new([Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary).WithOptimizationLevel([Microsoft.CodeAnalysis.OptimizationLevel]::Release).WithDeterministic($true)
$compilation=[Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('PaddockCrewMapper',$trees,$references,$options)
$temporary=Join-Path $OutputDirectory ('mapper_core.building.'+[Guid]::NewGuid().ToString('N'))
$stream=[IO.File]::Create($temporary)
try{$result=$compilation.Emit($stream)}finally{$stream.Dispose()}
if(-not $result.Success){$result.Diagnostics | Where-Object Severity -eq Error | ForEach-Object {$_.ToString()}; Remove-Item -LiteralPath $temporary; throw 'Mapper build failed'}
$assemblyHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
$assemblyFile='mapper_core.'+$assemblyHash+'.dll';$target=Join-Path $OutputDirectory $assemblyFile
if(Test-Path -LiteralPath $target) {
    if((Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant() -ne $assemblyHash) { throw 'Versioned mapper assembly hash mismatch' }
    Remove-Item -LiteralPath $temporary
} else { Move-Item -LiteralPath $temporary -Destination $target }
$hashes=[ordered]@{}
foreach($name in $sourceNames){$hashes[$name]=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $assetRoot $name)).Hash.ToLowerInvariant()}
$dependencies=[ordered]@{}
foreach($name in @('Newtonsoft.Json.dll','FuzzySharp.dll','Phonix.dll','MathNet.Numerics.dll')){$dependencies[$name]=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $CrewChiefDirectory $name)).Hash.ToLowerInvariant()}
$metadata=[ordered]@{}
foreach($name in @('fuel_speech.json','fuel_folders.json','pit_speech.json','pit_folders.json','position_speech.json','position_folders.json','lapcounter_folders.json','timing_speech.json','timing_folders.json','session_end_folders.json','tyre_speech.json','tyre_folders.json','laptime_speech.json','laptime_folders.json')){$metadata[$name]=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $assetRoot $name)).Hash.ToLowerInvariant()}
$receiptTemporary=Join-Path $OutputDirectory 'mapper_core.build.json.tmp'
[ordered]@{version='4.19.5.4';framework='.NET Framework 4.8';language='C# 7.2';sources=$hashes;metadata=$metadata;dependencies=$dependencies;assembly_file=$assemblyFile;assembly_sha256=$assemblyHash} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptTemporary -Encoding utf8
Move-Item -LiteralPath $receiptTemporary -Destination (Join-Path $OutputDirectory 'mapper_core.build.json') -Force
Write-Output $target
