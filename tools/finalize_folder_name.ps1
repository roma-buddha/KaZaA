$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$projectParent = [IO.Path]::GetDirectoryName($sourceRoot)
$targetRoot = Join-Path $projectParent 'KaZaA'
$temporaryRoot = Join-Path $projectParent 'KaZaA-casing-update'
if ((Split-Path -Leaf $sourceRoot) -ine 'KaZaA') {
    throw 'This script only updates the capitalization of the KaZaA project folder.'
}
foreach ($candidate in @($sourceRoot, $targetRoot, $temporaryRoot)) {
    if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($candidate)) -cne $projectParent) {
        throw 'Unexpected rename target.'
    }
}
# Release this PowerShell process's own working-directory handle first.
Set-Location -LiteralPath $projectParent
if ((Get-Item -LiteralPath $sourceRoot).Name -cne 'KaZaA') {
    if (Test-Path -LiteralPath $temporaryRoot) { throw 'Temporary rename folder already exists.' }
    try {
        Rename-Item -LiteralPath $sourceRoot -NewName 'KaZaA-casing-update' -ErrorAction Stop
    } catch {
        throw 'Close Codex and KaZaA, then run this script again. A process still holds the project folder open.'
    }
    try { Rename-Item -LiteralPath $temporaryRoot -NewName 'KaZaA' -ErrorAction Stop }
    catch {
        Rename-Item -LiteralPath $temporaryRoot -NewName (Split-Path -Leaf $sourceRoot) -ErrorAction Stop
        throw
    }
}
& (Join-Path $targetRoot 'tools\install_shortcut.ps1')
Write-Output "Project folder: $targetRoot"
