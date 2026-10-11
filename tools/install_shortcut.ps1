$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$appIcon = Join-Path $projectRoot 'kazaa\ui\assets\icon-start1.ico'
if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $appIcon)) {
    throw 'Set up the local desktop runtime and app icon first.'
}
$desktopRoot = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopRoot 'KaZaA.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.Arguments = '-m kazaa'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$appIcon,0"
$shortcut.Description = 'KaZaA'
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
# Windows treats differently capitalized shortcut names as the same path.
# A temporary hop also updates the spelling displayed by Explorer.
$existing = Get-ChildItem -LiteralPath $desktopRoot -Filter '*.lnk' |
    Where-Object { $_.Name -ieq 'KaZaA.lnk' -and $_.Name -cne 'KaZaA.lnk' }
foreach ($item in $existing) {
    $temporaryShortcut = Join-Path $desktopRoot ('kazaa-shortcut-{0}.lnk' -f [guid]::NewGuid())
    Move-Item -LiteralPath $item.FullName -Destination $temporaryShortcut
    Move-Item -LiteralPath $temporaryShortcut -Destination $shortcutPath
}
Write-Output "Verified desktop shortcut: $shortcutPath"
