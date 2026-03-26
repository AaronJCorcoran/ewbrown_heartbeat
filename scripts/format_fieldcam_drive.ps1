#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Formats a drive as exFAT with label FIELDCAM and creates the cam1/cam2 folder structure.
    Run as Administrator. Process one drive at a time in a loop.
#>

$LABEL         = "FIELDCAM"
$FOLDERS       = @("cam1", "cam2")
$ALLOC_UNIT_KB = 128   # 128 KB allocation unit - good for large sequential video files

function Show-Disks {
    Write-Host ""
    Write-Host "Available non-system disks:" -ForegroundColor Cyan
    Write-Host ("-" * 60)

    $disks = Get-Disk | Where-Object { $_.IsSystem -eq $false -and $_.IsBoot -eq $false }

    if ($disks.Count -eq 0) {
        Write-Host "  No non-system disks found. Connect a drive and try again." -ForegroundColor Yellow
        return $null
    }

    foreach ($disk in $disks) {
        $sizeGB = [math]::Round($disk.Size / 1GB, 1)
        $partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue
        $letters = ($partitions | Where-Object { $_.DriveLetter } | ForEach-Object { $_.DriveLetter + ":" }) -join ", "
        if (-not $letters) { $letters = "(no letter)" }
        Write-Host ("  [{0}]  {1} GB   {2}   {3}" -f $disk.Number, $sizeGB, $disk.FriendlyName, $letters)
    }

    Write-Host ("-" * 60)
    return $disks
}

function Format-FieldcamDrive {
    param([int]$DiskNumber)

    $disk = Get-Disk -Number $DiskNumber
    $sizeGB = [math]::Round($disk.Size / 1GB, 1)

    Write-Host ""
    Write-Host ("Selected: Disk {0} - {1} GB - {2}" -f $DiskNumber, $sizeGB, $disk.FriendlyName) -ForegroundColor Yellow
    Write-Host ""
    Write-Host "WARNING: This will ERASE ALL DATA on this disk." -ForegroundColor Red
    $confirm = Read-Host "Type YES to continue"

    if ($confirm -ne "YES") {
        Write-Host "Cancelled." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "Step 1/4: Clearing disk $DiskNumber..." -ForegroundColor Cyan
    Clear-Disk -Number $DiskNumber -RemoveData -Confirm:$false

    Write-Host "Step 2/4: Initializing GPT partition table..." -ForegroundColor Cyan
    Initialize-Disk -Number $DiskNumber -PartitionStyle GPT

    Write-Host "Step 3/4: Creating partition and formatting exFAT ($LABEL)..." -ForegroundColor Cyan
    $partition = New-Partition -DiskNumber $DiskNumber -UseMaximumSize -AssignDriveLetter
    $letter = $partition.DriveLetter

    # Brief pause - Windows needs a moment before Format-Volume can proceed
    Start-Sleep -Seconds 2

    Format-Volume `
        -DriveLetter $letter `
        -FileSystem exFAT `
        -NewFileSystemLabel $LABEL `
        -AllocationUnitSize ($ALLOC_UNIT_KB * 1024) `
        -Confirm:$false | Out-Null

    Write-Host "Step 4/4: Creating folder structure..." -ForegroundColor Cyan
    foreach ($folder in $FOLDERS) {
        $path = "${letter}:\${folder}"
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-Host "  Created $path"
    }

    Write-Host ""
    Write-Host ("Done. Drive {0}: is ready - label={1}, folders={2}" -f $letter, $LABEL, ($FOLDERS -join ", ")) -ForegroundColor Green
}

# -- Main loop -----------------------------------------------------------------

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  FIELDCAM Drive Formatter" -ForegroundColor Cyan
Write-Host "  Label: $LABEL  |  Filesystem: exFAT" -ForegroundColor Cyan
Write-Host "  Folders: $($FOLDERS -join ', ')" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

while ($true) {
    $disks = Show-Disks

    if ($null -eq $disks) {
        $retry = Read-Host "Press Enter to refresh, or type Q to quit"
        if ($retry -eq "Q") { break }
        continue
    }

    Write-Host ""
    $input = Read-Host "Enter disk number to format (or Q to quit)"

    if ($input -eq "Q") { break }

    if ($input -match '^\d+$') {
        $num = [int]$input
        $valid = $disks | Where-Object { $_.Number -eq $num }
        if ($valid) {
            Format-FieldcamDrive -DiskNumber $num
        } else {
            Write-Host "Disk $num is not in the list above (or is a system disk)." -ForegroundColor Red
        }
    } else {
        Write-Host "Invalid input." -ForegroundColor Red
    }

    Write-Host ""
    $next = Read-Host "Format another drive? (Enter to continue, Q to quit)"
    if ($next -eq "Q") { break }
}

Write-Host ""
Write-Host "Exiting." -ForegroundColor Cyan
