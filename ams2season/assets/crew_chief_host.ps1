param([Parameter(Mandatory=$true)][string]$Library)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    [Reflection.Assembly]::LoadFrom($Library) | Out-Null
    Add-Type -Path (Join-Path $PSScriptRoot 'crew_chief_host.cs') -ReferencedAssemblies @($Library, 'System.Web.Extensions', 'System.Core', 'System')
    $initial = [Console]::ReadLine() | ConvertFrom-Json
    [PaddockRadioHost]::Run([int]$initial.port, [string]$initial.token, [bool]$initial.allow_audio)
} catch {
    [Console]::WriteLine((@{type='error';error=$_.Exception.Message} | ConvertTo-Json -Compress))
}
