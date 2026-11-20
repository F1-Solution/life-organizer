<#
.SYNOPSIS
    Read-only export of daily recurring series from the default classic Outlook calendar, with their full description.
.EXAMPLE
    pwsh -NoProfile -File outlook_daily.ps1 -ActiveSince 2026-08-01 -OutFile C:\work\life\output\daily.json
#>
[CmdletBinding()]
param(
    [datetime]$ActiveSince = '2026-08-01',
    [Parameter(Mandatory)][string]$OutFile
)
$ErrorActionPreference = 'Stop'

$wasRunning = [bool](Get-Process -Name OUTLOOK -ErrorAction SilentlyContinue)
# The "new Outlook" toggle redirects classic Outlook and breaks COM: switch it off only while reading.
$prefsKey = 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences'
$useNewOutlook = (Get-ItemProperty -Path $prefsKey -ErrorAction SilentlyContinue).UseNewOutlook
if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 0 }

$outlook = $null
try {
    $outlook = New-Object -ComObject Outlook.Application
    # 9 = olFolderCalendar; IncludeRecurrences stays off so each series appears once as its master.
    $items = $outlook.GetNamespace('MAPI').GetDefaultFolder(9).Items
    $series = foreach ($item in $items) {
        if (-not $item.IsRecurring) { continue }
        $pattern = $item.GetRecurrencePattern()
        # 0 = olRecursDaily
        if ($pattern.RecurrenceType -ne 0) { continue }
        if (-not $pattern.NoEndDate -and $pattern.PatternEndDate -lt $ActiveSince) { continue }
        [pscustomobject][ordered]@{
            subject     = $item.Subject
            series_from = $pattern.PatternStartDate.ToString('yyyy-MM-dd')
            series_to   = if ($pattern.NoEndDate) { $null } else { $pattern.PatternEndDate.ToString('yyyy-MM-dd') }
            interval    = $pattern.Interval
            categories  = $item.Categories
            body        = ([string]$item.Body).Trim()
        }
    }
}
finally {
    if ($outlook) {
        if (-not $wasRunning) { $outlook.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($outlook)
    }
    if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 1 }
}

Set-Content -Path $OutFile -Value (ConvertTo-Json -InputObject @($series) -Depth 3) -Encoding utf8
Write-Host "$(@($series).Count) daily series -> $OutFile"
