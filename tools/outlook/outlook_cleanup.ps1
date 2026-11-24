<#
.SYNOPSIS
    Delete the handled daily series listed by outlook_handled.py, re-checking each one; without -Apply it only lists them.
.EXAMPLE
    pwsh -NoProfile -File outlook_cleanup.ps1 -Plan C:\work\life\output\plan.json -LogFile C:\work\life\data\outlook\eventi-cancellati.jsonl -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$LogFile,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

$planned = @{}
foreach ($p in (Get-Content -Raw -Path $Plan | ConvertFrom-Json)) {
    # analizzata = every link has an analysed Scheda; trascritta = the to-do is already in Google Tasks "Da fare" or in Idee.md.
    if ($p.stato -notin @('analizzata', 'trascritta')) { continue }
    $planned[$p.entry_id] = $p
}
if ($planned.Count -eq 0) { Write-Host 'Nothing to delete.'; return }

$wasRunning = [bool](Get-Process -Name OUTLOOK -ErrorAction SilentlyContinue)
# The "new Outlook" toggle breaks COM: switch it off only while working.
$prefsKey = 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences'
$useNewOutlook = (Get-ItemProperty -Path $prefsKey -ErrorAction SilentlyContinue).UseNewOutlook
if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 0 }

$outlook = $null
$count = 0
try {
    $outlook = New-Object -ComObject Outlook.Application
    $ns = $outlook.GetNamespace('MAPI')
    $me = $ns.CurrentUser.Name
    # 9 = olFolderCalendar; collect first, then delete, so the collection is not changed while iterating.
    $targets = foreach ($item in @($ns.GetDefaultFolder(9).Items)) {
        $p = $planned[$item.EntryID]
        if (-not $p) { continue }
        if (-not $item.IsRecurring) { continue }
        $pattern = $item.GetRecurrencePattern()
        if ($pattern.RecurrenceType -ne 0) { continue }
        if ($item.Recipients.Count -gt 1) { continue }
        # 0 = olNonMeeting: the recipient count alone is unreliable on recurring masters.
        if ($item.MeetingStatus -ne 0) { continue }
        if ($item.Organizer -ne $me) { continue }
        if ($item.Subject -ne $p.subject) { continue }
        $item
    }
    foreach ($item in @($targets)) {
        $entry = [ordered]@{ entry_id = $item.EntryID; subject = $item.Subject; motivo = 'gestito'; ora = (Get-Date).ToUniversalTime().ToString('o') }
        Write-Host ("{0} {1}" -f ($(if ($Apply) { 'DELETE' } else { 'would delete' }), $item.Subject))
        if ($Apply) {
            $item.Delete()
            Add-Content -Path $LogFile -Value (ConvertTo-Json -InputObject $entry -Compress) -Encoding utf8
        }
        $count++
    }
}
finally {
    if ($outlook) {
        if (-not $wasRunning) { $outlook.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($outlook)
    }
    if ($useNewOutlook -eq 1) { Set-ItemProperty -Path $prefsKey -Name UseNewOutlook -Value 1 }
}
Write-Host "$count series $(if ($Apply) { 'deleted' } else { 'to delete (dry run)' }) of $($planned.Count) planned"
