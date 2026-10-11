$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonLauncher = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $PSScriptRoot 'KaZaA.exe'
$appIcon = Join-Path $projectRoot 'kazaa\ui\assets\icon-start1.ico'
if (-not (Test-Path -LiteralPath $pythonLauncher) -or -not (Test-Path -LiteralPath $appIcon)) {
    throw 'Set up the local desktop runtime and app icon first.'
}
if (-not ('KaZaAShortcutIdentity' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'shortcut_identity.cs')
}
$desktopRoot = [Environment]::GetFolderPath('Desktop')
$programsRoot = [Environment]::GetFolderPath('Programs')
$shortcutShell = New-Object -ComObject WScript.Shell
$propertyShell = New-Object -ComObject Shell.Application
$backupRoot = Join-Path $projectRoot ('tools\out\shortcuts\' + [guid]::NewGuid())
$appId = 'KaZaA.Desktop.Start1'
$displayName = 'KaZaA'
$registration = 'HKCU:\Software\Classes\AppUserModelId\' + $appId
$previous = Get-ItemProperty -LiteralPath $registration -ErrorAction SilentlyContinue
if ($previous -and $previous.InstallationRoot -ne $projectRoot) {
    throw 'Another installation owns this application identity. Its registration was preserved.'
}
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET compiler is required to create the desktop launcher.' }
$temporaryLauncher = Join-Path $projectRoot ('tools\out\launcher-' + [guid]::NewGuid() + '.exe')
New-Item -ItemType Directory -Path (Split-Path $temporaryLauncher) -Force | Out-Null
& $compiler /nologo /target:winexe /reference:System.Windows.Forms.dll "/win32icon:$appIcon" "/out:$temporaryLauncher" (Join-Path $PSScriptRoot 'windows_launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows desktop launcher compilation failed.' }
if ((Get-Item -LiteralPath $temporaryLauncher).VersionInfo.ProductName -cne 'KaZaA') {
    throw 'Launcher display-name verification failed.'
}
if (Test-Path -LiteralPath $launcher) {
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    Copy-Item -LiteralPath $launcher -Destination (Join-Path $backupRoot 'KaZaA.exe')
}
Move-Item -LiteralPath $temporaryLauncher -Destination $launcher -Force

# Only replace shortcuts belonging to this checkout; preserve legacy installs.
foreach ($shortcutRoot in @($desktopRoot, $programsRoot)) {
    # The old Desktop URL keeps its cached casing even after reindexing. Fresh
    # paths give Search a new item while the visible shortcut stays just KaZaA.
    $destinationRoot = if ($shortcutRoot -eq $programsRoot) { Join-Path $shortcutRoot 'KaZaA Desktop' } else { Join-Path $shortcutRoot 'KaZaA' }
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
    if ($destinationRoot -ne $shortcutRoot) { [KaZaAShortcutIdentity]::NotifyFolder($destinationRoot) }
    $shortcutName = $displayName + '.lnk'
    $destination = Join-Path $destinationRoot $shortcutName
    $existing = @(Get-ChildItem -LiteralPath $shortcutRoot -Filter '*.lnk' -Recurse | Where-Object {
        $link = $shortcutShell.CreateShortcut($_.FullName)
        ($link.TargetPath -ieq $pythonLauncher -and $link.Arguments.Trim() -eq '-m kazaa') -or
        ($link.TargetPath -ieq $launcher -and $link.Arguments.Trim() -eq '')
    })
    if ((Test-Path -LiteralPath $destination) -and $destination -notin $existing.FullName) {
        throw "Another installation owns $destination. Its shortcut was preserved."
    }
    $temporary = Join-Path $shortcutRoot ('kazaa-shortcut-' + [guid]::NewGuid() + '.lnk')
    $link = $shortcutShell.CreateShortcut($temporary)
    $link.TargetPath = $launcher
    $link.Arguments = ''
    $link.WorkingDirectory = $projectRoot
    $link.IconLocation = "$appIcon,0"
    $link.Description = $displayName
    $link.Save()
    [KaZaAShortcutIdentity]::Set($temporary)
    $backups = @()
    try {
        foreach ($item in $existing) {
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            $backup = Join-Path $backupRoot ([guid]::NewGuid().ToString() + '.lnk')
            Move-Item -LiteralPath $item.FullName -Destination $backup
            $backups += [pscustomobject]@{Original=$item.FullName; Backup=$backup}
            [KaZaAShortcutIdentity]::Notify($item.FullName, $true)
            if ($shortcutRoot -eq $desktopRoot) {
                try { [KaZaAShortcutIdentity]::RefreshIndex($item.FullName) } catch { Write-Warning "Could not refresh Search for $($item.FullName): $_" }
            }
        }
        Move-Item -LiteralPath $temporary -Destination $destination
        [KaZaAShortcutIdentity]::Notify($destination, $false)
        if ($shortcutRoot -eq $desktopRoot) {
            try { [KaZaAShortcutIdentity]::RefreshIndex($destination) } catch { Write-Warning "Could not refresh Search for ${destination}: $_" }
        }
        $verified = $shortcutShell.CreateShortcut($destination)
        $folder = $propertyShell.NameSpace($destinationRoot)
        $identity = $folder.ParseName($shortcutName).ExtendedProperty('System.AppUserModel.ID')
        $actualName = (Get-Item -LiteralPath $destination).Name
        if ($actualName -cne $shortcutName -or $identity -cne $appId -or
            $verified.TargetPath -ne $launcher -or $verified.WorkingDirectory -ne $projectRoot -or
            $verified.Arguments -ne '' -or $verified.IconLocation -ne "$appIcon,0") {
            throw 'Shortcut name, identity or launch verification failed.'
        }
        Write-Output "Verified shortcut: $destination ($appId)"
    } catch {
        if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination }
        foreach ($backup in $backups) { Move-Item -LiteralPath $backup.Backup -Destination $backup.Original }
        throw
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}
New-Item -Path $registration -Force | Out-Null
foreach ($value in @{ DisplayName=$displayName; IconUri=$appIcon; InstallationRoot=$projectRoot }.GetEnumerator()) {
    New-ItemProperty -LiteralPath $registration -Name $value.Key -Value $value.Value -PropertyType String -Force | Out-Null
}
if ((Get-ItemProperty -LiteralPath $registration).DisplayName -cne $displayName) {
    throw 'Windows application display-name verification failed.'
}
Write-Output "Verified registered display name: $displayName ($appId)"
Get-StartApps | Where-Object { $_.AppID -eq $appId } | Format-Table Name,AppID
