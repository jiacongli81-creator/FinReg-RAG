param(
    [string]$InputDir = "$PSScriptRoot\..\data\raw",
    [string]$OutputDir = "$PSScriptRoot\..\data\converted",
    [string]$ReportPath = "$PSScriptRoot\..\data\conversion_report.csv"
)

$ErrorActionPreference = "Stop"
$InputDir = [System.IO.Path]::GetFullPath($InputDir)
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)
$legacyExtensions = @('.doc', '.wps')
$files = @(Get-ChildItem -LiteralPath $InputDir -Recurse -File | Where-Object { $legacyExtensions -contains $_.Extension.ToLowerInvariant() })
$rows = New-Object System.Collections.Generic.List[object]
$word = $null

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    foreach ($source in $files) {
        $relative = $source.FullName.Substring($InputDir.TrimEnd('\').Length).TrimStart('\')
        $target = Join-Path $OutputDir ([System.IO.Path]::ChangeExtension($relative, '.docx'))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        $document = $null
        $status = 'failed'
        $errorText = ''
        try {
            $document = $word.Documents.Open($source.FullName, $false, $true, $false)
            $document.SaveAs2($target, 16)
            $status = 'converted'
            Write-Host "[$status] $($source.Name)"
        } catch {
            $errorText = $_.Exception.Message.Replace("`r", ' ').Replace("`n", ' ')
            Write-Host "[$status] $($source.Name) - $errorText"
        } finally {
            if ($null -ne $document) {
                try { $document.Close($false) } catch { }
                [System.Runtime.InteropServices.Marshal]::ReleaseComObject($document) | Out-Null
            }
        }
        $rows.Add([pscustomobject]@{ source = $source.FullName; target = $target; status = $status; error = $errorText })
    }
} finally {
    if ($null -ne $word) {
        try { $word.Quit($false) } catch { }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$rows | Export-Csv -LiteralPath $ReportPath -NoTypeInformation -Encoding UTF8
$converted = @($rows | Where-Object status -eq 'converted').Count
$failed = @($rows | Where-Object status -eq 'failed').Count
Write-Host "Done: total=$($rows.Count), converted=$converted, failed=$failed"
Write-Host "Output: $OutputDir"
Write-Host "Report: $ReportPath"
if ($failed -gt 0) { exit 1 }
