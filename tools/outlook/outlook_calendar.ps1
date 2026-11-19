<#
.SYNOPSIS
    Read-only export of the default calendar from classic Outlook via COM (never touches mail).
.EXAMPLE
    pwsh -NoProfile -File outlook_calendar.ps1 -Days 7
    pwsh -NoProfile -File outlook_calendar.ps1 -Start 2026-11-01 -Days 30 -Format json -OutFile C:\work\life\output\cal.json
#>
[CmdletBinding()]
param(
    [datetime]$Start = (Get-Date).Date,
    [ValidateRange(1, 366)][int]$Days = 7,
    [switch]$Details,
    [ValidateSet('table', 'json')][string]$Format = 'table',
    [string]$OutFile,
    [int]$MaxItems = 2000
)
$ErrorActionPreference = 'Stop'

$busyNames = @{ 0 = 'free'; 1 = 'tentative'; 2 = 'busy'; 3 = 'oof'; 4 = 'elsewhere' }
$responseNames = @{ 0 = 'none'; 1 = 'organizer'; 2 = 'tentative'; 3 = 'accepted'; 4 = 'declined'; 5 = 'not_responded' }

function ConvertTo-EventRecord($item, [bool]$withDetails) {
    $record = [ordered]@{
        start      = $item.Start.ToString('s')
        end        = $item.End.ToString('s')
        all_day    = [bool]$item.AllDayEvent
        subject    = $item.Subject
        location   = $item.Location
        busy       = $busyNames[[int]$item.BusyStatus]
        response   = $responseNames[[int]$item.ResponseStatus]
        recurring  = [bool]$item.IsRecurring
        categories = $item.Categories
    }
    if ($withDetails) {
        $record.organizer = $item.Organizer
        $record.required = $item.RequiredAttendees
        $record.optional = $item.OptionalAttendees
        $body = [string]$item.Body
        $record.body = if ($body.Length -gt 500) { $body.Substring(0, 500) + '…' } else { $body }
    }
    [pscustomobject]$record
}

$end = $Start.AddDays($Days)
$wasRunning = [bool](Get-Process -Name OUTLOOK -ErrorAction SilentlyContinue)

# The "new Outlook" toggle redirects classic Outlook and breaks COM: switch it off only while reading.
$prefsKey = 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences'
$useNewOutlook = (Get-ItemProperty -Path $prefsKey -ErrorAction SilentlyContinue).UseNewOutlook
if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 0 }

$outlook = $null
try {
    $outlook = New-Object -ComObject Outlook.Application
    # 9 = olFolderCalendar: the only folder this tool reads.
    $calendar = $outlook.GetNamespace('MAPI').GetDefaultFolder(9)
    $items = $calendar.Items
    $items.Sort('[Start]')
    $items.IncludeRecurrences = $true
    $culture = [Globalization.CultureInfo]::CurrentCulture
    $filter = "[Start] < '{0}' AND [End] > '{1}'" -f $end.ToString('g', $culture), $Start.ToString('g', $culture)
    $found = $items.Restrict($filter)

    $events = @(
        $item = $found.GetFirst()
        $count = 0
        while ($null -ne $item -and $count -lt $MaxItems) {
            ConvertTo-EventRecord $item $Details.IsPresent
            $count++
            $item = $found.GetNext()
        }
    )
}
finally {
    if ($outlook) {
        if (-not $wasRunning) { $outlook.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($outlook)
    }
    if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 1 }
}

$text = if ($Format -eq 'json') {
    ConvertTo-Json -InputObject $events -Depth 3
}
else {
    $events | Format-Table start, end, subject, location, busy -AutoSize | Out-String -Width 220
}
if ($OutFile) {
    Set-Content -Path $OutFile -Value $text -Encoding utf8
    Write-Host "$($events.Count) events -> $OutFile"
}
else {
    $text
}
