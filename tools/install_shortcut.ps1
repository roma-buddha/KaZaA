$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$appIcon = Join-Path $projectRoot 'kazaa\ui\assets\icon-start1.ico'
if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $appIcon)) {
    throw 'Set up the local desktop runtime and app icon first.'
}
$desktopRoot = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopRoot 'KazaA.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.Arguments = '-m kazaa'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$appIcon,0"
$shortcut.Description = 'KazaA'
$shortcut.Save()
$verified = $shortcutShell.CreateShortcut($shortcutPath)
if ($verified.TargetPath -ne $launcher -or $verified.WorkingDirectory -ne $projectRoot -or
    $verified.Arguments -ne '-m kazaa' -or $verified.IconLocation -ne "$appIcon,0") {
    throw 'Shortcut verification failed.'
}
$oldShortcut = Join-Path $desktopRoot 'VLoader.lnk'
if (Test-Path -LiteralPath $oldShortcut) {
    $backupRoot = Join-Path $projectRoot 'tools\out\shortcuts'
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $backupPath = Join-Path $backupRoot ('VLoader-{0}.lnk' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Move-Item -LiteralPath $oldShortcut -Destination $backupPath
}
Write-Output "Verified desktop shortcut: $shortcutPath"
