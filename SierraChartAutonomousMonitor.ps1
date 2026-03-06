# SierraChartAutonomousMonitor.ps1
# Autonomous background monitor for Sierra Chart window management
# Runs continuously, auto-saves positions, auto-restores on launch

# CRITICAL: param() MUST be first statement after comments
param(
    [int]$CheckIntervalSeconds = 30,        # How often to check for Sierra Chart (increased to 30 to prevent flicker)
    [int]$AutoSaveIntervalMinutes = 5,      # How often to auto-save positions
    [int]$RestoreDelaySeconds = 5           # Delay after detecting Sierra Chart launch
)

# Configuration
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateFilePath = Join-Path $ScriptDir "sierra_chart_window_state.json"
$LogFilePath = Join-Path $ScriptDir "autonomous_monitor.log"
$PidFilePath = Join-Path $ScriptDir "autonomous_monitor.pid"
$WindowManagerPath = Join-Path $ScriptDir "SierraChartWindowManager.ps1"

# FIXED: Multiple process name patterns to check
# Sierra Chart can appear as: SierraChart_64, SierraChart, sierra, SC, SierraChart64
$SierraChartProcessPatterns = @(
    "SierraChart_64",
    "SierraChart64",
    "SierraChart",
    "sierra"
)

# Logging function with rotation
function Write-MonitorLog {
    param([string]$Message, [string]$Level = "INFO")

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"

    # Console output
    Write-Host $logMessage

    # File output with rotation
    try {
        # Rotate log if > 10MB
        if (Test-Path $LogFilePath) {
            $logSize = (Get-Item $LogFilePath).Length
            if ($logSize -gt 10MB) {
                $archivePath = "$LogFilePath.$(Get-Date -Format 'yyyyMMdd_HHmmss').old"
                Move-Item $LogFilePath $archivePath -Force
                Write-Host "Log rotated to: $archivePath"

                # Keep only last 3 archived logs
                Get-ChildItem -Path $ScriptDir -Filter "autonomous_monitor.log.*.old" |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -Skip 3 |
                    ForEach-Object { Remove-Item $_.FullName -Force }
            }
        }

        Add-Content -Path $LogFilePath -Value $logMessage -ErrorAction SilentlyContinue
    }
    catch {
        Write-Host "Failed to write to log: $_"
    }
}

# FIXED: Flexible Sierra Chart process detection
function Test-SierraChartRunning {
    # Check each pattern
    foreach ($pattern in $SierraChartProcessPatterns) {
        $process = Get-Process -Name $pattern -ErrorAction SilentlyContinue
        if ($process) {
            return $true
        }
    }

    # Fallback: wildcard search
    $wildcardSearch = Get-Process | Where-Object {
        $_.ProcessName -match "sierra" -or
        $_.ProcessName -match "SierraChart"
    } | Select-Object -First 1

    return $null -ne $wildcardSearch
}

# Get Sierra Chart process name (for logging)
function Get-SierraChartProcessInfo {
    foreach ($pattern in $SierraChartProcessPatterns) {
        $process = Get-Process -Name $pattern -ErrorAction SilentlyContinue
        if ($process) {
            return @{
                Name = $pattern
                Id = $process.Id
                Count = @($process).Count
            }
        }
    }

    # Fallback
    $wildcardSearch = Get-Process | Where-Object {
        $_.ProcessName -match "sierra" -or
        $_.ProcessName -match "SierraChart"
    } | Select-Object -First 1

    if ($wildcardSearch) {
        return @{
            Name = $wildcardSearch.ProcessName
            Id = $wildcardSearch.Id
            Count = 1
        }
    }

    return $null
}

# Auto-save window positions
function Invoke-AutoSave {
    Write-MonitorLog "Auto-saving window positions..."

    if (-not (Test-Path $WindowManagerPath)) {
        Write-MonitorLog "Window manager script not found: $WindowManagerPath" "ERROR"
        return $false
    }

    try {
        # Run in same session for better reliability but HIDDEN
        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = "powershell.exe"
        $pinfo.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"$WindowManagerPath`" -Save"
        $pinfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $pinfo.CreateNoWindow = $true
        $pinfo.UseShellExecute = $false
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $pinfo
        $process.Start() | Out-Null
        
        $output = $process.StandardOutput.ReadToEnd()
        $error = $process.StandardError.ReadToEnd()
        
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        $result = "$output`n$error"

        if ($exitCode -eq 0) {
            Write-MonitorLog "Auto-save successful" "SUCCESS"
            return $true
        }
        else {
            Write-MonitorLog "Auto-save failed with exit code: $exitCode" "WARNING"
            Write-MonitorLog "Output: $result" "DEBUG"
            return $false
        }
    }
    catch {
        Write-MonitorLog "Auto-save error: $_" "ERROR"
        return $false
    }
}

# Auto-restore window positions with retry logic
function Invoke-AutoRestore {
    param([int]$DelaySeconds = 5)

    Write-MonitorLog "Auto-restoring window positions (delay: ${DelaySeconds}s)..."

    if (-not (Test-Path $WindowManagerPath)) {
        Write-MonitorLog "Window manager script not found: $WindowManagerPath" "ERROR"
        return $false
    }

    # Wait for Sierra Chart to fully initialize
    if ($DelaySeconds -gt 0) {
        Write-MonitorLog "Waiting ${DelaySeconds}s for Sierra Chart to initialize..."
        Start-Sleep -Seconds $DelaySeconds
    }

    # Retry logic - sometimes first attempt fails if windows not ready
    $maxRetries = 3
    $retryDelay = 2

    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        try {
            Write-MonitorLog "Restore attempt $attempt of $maxRetries..."

            $pinfo = New-Object System.Diagnostics.ProcessStartInfo
            $pinfo.FileName = "powershell.exe"
            $pinfo.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"$WindowManagerPath`" -Restore -DelaySeconds 0"
            $pinfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            $pinfo.CreateNoWindow = $true
            $pinfo.UseShellExecute = $false
            $pinfo.RedirectStandardOutput = $true
            $pinfo.RedirectStandardError = $true

            $process = New-Object System.Diagnostics.Process
            $process.StartInfo = $pinfo
            $process.Start() | Out-Null
            
            $output = $process.StandardOutput.ReadToEnd()
            $error = $process.StandardError.ReadToEnd()
            
            $process.WaitForExit()
            $exitCode = $process.ExitCode
            $result = "$output`n$error"

            if ($exitCode -eq 0) {
                Write-MonitorLog "Auto-restore successful on attempt $attempt" "SUCCESS"
                return $true
            }
            else {
                Write-MonitorLog "Restore attempt $attempt failed (exit code: $exitCode)" "WARNING"

                if ($attempt -lt $maxRetries) {
                    Write-MonitorLog "Retrying in ${retryDelay}s..."
                    Start-Sleep -Seconds $retryDelay
                }
            }
        }
        catch {
            Write-MonitorLog "Restore attempt $attempt error: $_" "ERROR"

            if ($attempt -lt $maxRetries) {
                Start-Sleep -Seconds $retryDelay
            }
        }
    }

    Write-MonitorLog "Auto-restore failed after $maxRetries attempts" "ERROR"
    return $false
}

# Write PID file
function Write-PidFile {
    try {
        $PID | Set-Content -Path $PidFilePath -Force
        Write-MonitorLog "PID file created: $PidFilePath (PID: $PID)"
    }
    catch {
        Write-MonitorLog "Failed to create PID file: $_" "WARNING"
    }
}

# Remove PID file
function Remove-PidFile {
    try {
        if (Test-Path $PidFilePath) {
            Remove-Item $PidFilePath -Force
            Write-MonitorLog "PID file removed"
        }
    }
    catch {
        Write-MonitorLog "Failed to remove PID file: $_" "WARNING"
    }
}

# Check if monitor is already running
function Test-MonitorRunning {
    if (-not (Test-Path $PidFilePath)) {
        return $false
    }

    try {
        $existingPid = Get-Content -Path $PidFilePath -ErrorAction Stop
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue

        if ($existingProcess) {
            # Check if it's actually this script (PowerShell process)
            if ($existingProcess.ProcessName -eq "powershell" -or $existingProcess.ProcessName -eq "pwsh") {
                return $true
            }
        }

        # Stale PID file - remove it
        Remove-Item $PidFilePath -Force
        return $false
    }
    catch {
        return $false
    }
}

# Main monitoring loop
function Start-AutonomousMonitoring {
    Write-MonitorLog "========================================" "INFO"
    Write-MonitorLog "Autonomous Monitor Started (FIXED v2.1 - NO FLICKER)" "INFO"
    Write-MonitorLog "========================================" "INFO"
    Write-MonitorLog "Check Interval: ${CheckIntervalSeconds}s"
    Write-MonitorLog "Auto-Save Interval: ${AutoSaveIntervalMinutes}m"
    Write-MonitorLog "Restore Delay: ${RestoreDelaySeconds}s"
    Write-MonitorLog "State File: $StateFilePath"
    Write-MonitorLog "Log File: $LogFilePath"
    Write-MonitorLog "Window Manager: $WindowManagerPath"
    Write-MonitorLog "Process Patterns: $($SierraChartProcessPatterns -join ', ')"
    Write-MonitorLog "PID: $PID"
    Write-MonitorLog "========================================" "INFO"

    # Verify window manager exists
    if (-not (Test-Path $WindowManagerPath)) {
        Write-MonitorLog "CRITICAL: Window manager not found: $WindowManagerPath" "ERROR"
        Write-MonitorLog "Monitor cannot function without window manager. Exiting." "ERROR"
        return
    }

    # Write PID file
    Write-PidFile

    # State tracking
    $wasSierraRunning = $false
    $lastAutoSaveTime = Get-Date
    $windowsRestored = $false
    $consecutiveChecks = 0

    # Check if Sierra Chart is already running at startup
    $initialCheck = Test-SierraChartRunning
    if ($initialCheck) {
        $processInfo = Get-SierraChartProcessInfo
        Write-MonitorLog "Sierra Chart already running at monitor startup: $($processInfo.Name) (PID: $($processInfo.Id))" "INFO"
        $wasSierraRunning = $true

        # Don't auto-restore on monitor startup if Sierra already running
        # (user may have manually positioned windows)
        Write-MonitorLog "Skipping initial restore - Sierra Chart was already running" "INFO"
    }

    # Main loop
    try {
        while ($true) {
            $isSierraRunning = Test-SierraChartRunning

            # Detect Sierra Chart launch (wasn't running, now is)
            if ($isSierraRunning -and -not $wasSierraRunning) {
                $processInfo = Get-SierraChartProcessInfo
                Write-MonitorLog "========================================" "SUCCESS"
                Write-MonitorLog "Sierra Chart LAUNCH detected!" "SUCCESS"
                Write-MonitorLog "Process: $($processInfo.Name) (PID: $($processInfo.Id))" "SUCCESS"
                Write-MonitorLog "========================================" "SUCCESS"

                # Reset consecutive checks
                $consecutiveChecks = 0

                # Auto-restore windows on launch - DISABLED TO PREVENT FLICKERING
                # The continuous restoration loop was causing the application to flicker/stutter
                # Users can manually run the Restore-WindowState script if needed
                Write-MonitorLog "Auto-restore disabled to prevent flickering/fighting with manual moves." "INFO"
                Write-MonitorLog "To restore layout manually, run: .\SierraChartWindowManager.ps1 -Restore" "INFO"
                
                # if (Test-Path $StateFilePath) {
                #     Write-MonitorLog "Saved state found - initiating auto-restore..."
                #     $restored = Invoke-AutoRestore -DelaySeconds $RestoreDelaySeconds
                #     $windowsRestored = $restored
                # 
                #     if ($restored) {
                #         Write-MonitorLog "Windows restored successfully!" "SUCCESS"
                #     }
                #     else {
                #         Write-MonitorLog "Window restore had issues - will save current state instead" "WARNING"
                #         Start-Sleep -Seconds 3
                #         Invoke-AutoSave
                #     }
                # }
                # else {
                #     Write-MonitorLog "No saved state found - will save current layout after initialization" "INFO"
                #     # Give Sierra Chart time to create and position windows
                #     Start-Sleep -Seconds ($RestoreDelaySeconds + 3)
                #     Invoke-AutoSave
                # }

                # Reset auto-save timer
                $lastAutoSaveTime = Get-Date
            }

            # Detect Sierra Chart exit
            if (-not $isSierraRunning -and $wasSierraRunning) {
                Write-MonitorLog "========================================" "INFO"
                Write-MonitorLog "Sierra Chart EXIT detected" "INFO"
                Write-MonitorLog "========================================" "INFO"
                $windowsRestored = $false
                $consecutiveChecks = 0
            }

            # Auto-save periodically while Sierra Chart is running
            if ($isSierraRunning) {
                $consecutiveChecks++
                $timeSinceLastSave = (Get-Date) - $lastAutoSaveTime

                if ($timeSinceLastSave.TotalMinutes -ge $AutoSaveIntervalMinutes) {
                    Write-MonitorLog "Periodic auto-save triggered (every ${AutoSaveIntervalMinutes}m)"
                    Invoke-AutoSave
                    $lastAutoSaveTime = Get-Date
                }

                # Heartbeat log every 10 checks (5 minutes with 30s interval)
                if ($consecutiveChecks % 10 -eq 0) {
                    Write-MonitorLog "Heartbeat: Sierra Chart running for $($consecutiveChecks * $CheckIntervalSeconds)s, last save: $([int]$timeSinceLastSave.TotalMinutes)m ago" "DEBUG"
                }
            }

            # Update state
            $wasSierraRunning = $isSierraRunning

            # Sleep until next check
            Start-Sleep -Seconds $CheckIntervalSeconds
        }
    }
    catch {
        Write-MonitorLog "Fatal error in monitoring loop: $_" "ERROR"
        Write-MonitorLog $_.ScriptStackTrace "ERROR"
    }
    finally {
        Remove-PidFile
        Write-MonitorLog "Autonomous Monitor Stopped" "INFO"
    }
}

# Graceful shutdown handler
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-MonitorLog "Shutdown signal received - cleaning up..." "INFO"
    Remove-PidFile
}

# Check if already running
if (Test-MonitorRunning) {
    Write-MonitorLog "Autonomous monitor is already running!" "WARNING"
    Write-Host ""
    Write-Host "Another instance is already monitoring Sierra Chart." -ForegroundColor Yellow
    Write-Host "To stop it, run: Stop-Process -Id $(Get-Content $PidFilePath)" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Start monitoring
Start-AutonomousMonitoring