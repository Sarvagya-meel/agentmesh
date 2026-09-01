[CmdletBinding()]
param(
    [ValidateSet("Start", "Run", "Status", "Stop")]
    [string]$Action = "Start",

    [switch]$KeepDisplayOn,

    [ValidateRange(5, 300)]
    [int]$RefreshSeconds = 30,

    [string]$StateFile = (Join-Path ([System.IO.Path]::GetTempPath()) "agentmesh-keep-awake.json")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptPath = [System.IO.Path]::GetFullPath($PSCommandPath)

function Read-KeepAwakeState {
    if (-not (Test-Path -LiteralPath $StateFile -PathType Leaf)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-OwnedKeepAwakeProcess {
    param([object]$State)

    if ($null -eq $State -or $null -eq $State.process_id) {
        return $null
    }

    try {
        $processId = [int]$State.process_id
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    }
    catch {
        return $null
    }

    if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) {
        return $null
    }

    $commandLine = [string]$process.CommandLine
    $ownsProcess = $commandLine.IndexOf(
        $scriptPath,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -ge 0
    if (-not $ownsProcess -or $commandLine -notmatch '(?i)-Action\s+Run') {
        return $null
    }

    return $process
}

function Write-KeepAwakeStatus {
    $state = Read-KeepAwakeState
    $process = Get-OwnedKeepAwakeProcess -State $state
    if ($null -eq $process) {
        [pscustomobject]@{
            Status        = "Stopped"
            ProcessId     = $null
            KeepDisplayOn = $false
            StateFile     = $StateFile
        }
        return
    }

    [pscustomobject]@{
        Status         = "Running"
        ProcessId      = [int]$state.process_id
        KeepDisplayOn  = [bool]$state.keep_display_on
        RefreshSeconds = [int]$state.refresh_seconds
        StartedAt      = [string]$state.started_at
        StateFile      = $StateFile
    }
}

if ($Action -eq "Status") {
    Write-KeepAwakeStatus
    return
}

if ($Action -eq "Stop") {
    $state = Read-KeepAwakeState
    $process = Get-OwnedKeepAwakeProcess -State $state
    if ($null -ne $process) {
        Stop-Process -Id ([int]$state.process_id) -Force
    }
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    Write-KeepAwakeStatus
    return
}

if ($Action -eq "Start") {
    $existingState = Read-KeepAwakeState
    if ($null -ne (Get-OwnedKeepAwakeProcess -State $existingState)) {
        Write-KeepAwakeStatus
        return
    }

    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    $hostExecutable = (Get-Process -Id $PID).Path
    $quotedScriptPath = '"' + $scriptPath.Replace('"', '\"') + '"'
    $quotedStateFile = '"' + $StateFile.Replace('"', '\"') + '"'
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy Bypass",
        "-File $quotedScriptPath",
        "-Action Run",
        "-RefreshSeconds $RefreshSeconds",
        "-StateFile $quotedStateFile"
    )
    if ($KeepDisplayOn) {
        $arguments += "-KeepDisplayOn"
    }

    Start-Process `
        -FilePath $hostExecutable `
        -ArgumentList ($arguments -join " ") `
        -WindowStyle Hidden | Out-Null

    $started = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        Start-Sleep -Milliseconds 100
        $state = Read-KeepAwakeState
        if ($null -ne (Get-OwnedKeepAwakeProcess -State $state)) {
            $started = $true
            break
        }
    }

    if (-not $started) {
        throw "The keep-awake background process did not start."
    }

    Write-KeepAwakeStatus
    return
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class AgentMeshExecutionState
{
    private const uint ES_SYSTEM_REQUIRED = 0x00000001;
    private const uint ES_DISPLAY_REQUIRED = 0x00000002;
    private const uint ES_CONTINUOUS = 0x80000000;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint SetThreadExecutionState(uint executionState);

    public static bool PreventSleep(bool keepDisplayOn)
    {
        uint flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED;
        if (keepDisplayOn)
        {
            flags |= ES_DISPLAY_REQUIRED;
        }
        return SetThreadExecutionState(flags) != 0;
    }

    public static void RestoreDefaults()
    {
        SetThreadExecutionState(ES_CONTINUOUS);
    }
}
"@

if (-not [AgentMeshExecutionState]::PreventSleep($KeepDisplayOn.IsPresent)) {
    throw "Windows rejected the request to prevent automatic sleep."
}

$stateDirectory = Split-Path -Parent $StateFile
if (-not [string]::IsNullOrWhiteSpace($stateDirectory)) {
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
}

$state = [ordered]@{
    process_id       = $PID
    keep_display_on  = $KeepDisplayOn.IsPresent
    refresh_seconds  = $RefreshSeconds
    started_at       = [DateTimeOffset]::Now.ToString("O")
    script_path      = $scriptPath
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $StateFile,
    ($state | ConvertTo-Json -Compress),
    $utf8NoBom
)

try {
    while ($true) {
        Start-Sleep -Seconds $RefreshSeconds
        if (-not [AgentMeshExecutionState]::PreventSleep($KeepDisplayOn.IsPresent)) {
            throw "Windows rejected a keep-awake refresh request."
        }
    }
}
finally {
    [AgentMeshExecutionState]::RestoreDefaults()
    $currentState = Read-KeepAwakeState
    if ($null -ne $currentState -and [int]$currentState.process_id -eq $PID) {
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }
}
