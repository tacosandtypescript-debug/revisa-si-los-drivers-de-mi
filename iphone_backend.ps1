param(
    [ValidateSet('folders', 'files', 'copy')]
    [string]$Action = 'folders',
    [string]$Folder = '',
    [string]$SelectionsJson = '[]',
    [string]$Destination = ''
)

$ErrorActionPreference = 'Stop'

function Get-PhoneStorage {
    $shell = New-Object -ComObject Shell.Application
    $computer = $shell.NameSpace(17)
    if (-not $computer) { throw 'No se pudo abrir Este equipo.' }

    $phone = @($computer.Items()) |
        Where-Object { $_.Name -eq 'Apple iPhone' } |
        Select-Object -First 1
    if (-not $phone) { throw 'El iPhone no aparece en Este equipo. Desbloquéalo y pulsa Confiar.' }

    $storage = @($phone.GetFolder.Items()) |
        Where-Object { $_.Name -eq 'Internal Storage' } |
        Select-Object -First 1
    if (-not $storage) { throw 'No se encontró Internal Storage en el iPhone.' }

    return $storage
}

function Get-ItemDetail {
    param(
        [Parameter(Mandatory = $true)]$FolderObject,
        [Parameter(Mandatory = $true)]$ItemObject,
        [Parameter(Mandatory = $true)][int]$Index
    )
    try { return [string]$FolderObject.GetDetailsOf($ItemObject, $Index) }
    catch { return '' }
}

function New-FileId {
    param([string]$FolderName, [string]$FileName)
    $raw = "$FolderName|$FileName"
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw))
}

function Get-VideoFiles {
    param([Parameter(Mandatory = $true)]$StorageItem, [Parameter(Mandatory = $true)][string]$FolderName)

    $folderItem = @($StorageItem.GetFolder.Items()) |
        Where-Object { $_.IsFolder -and $_.Name -eq $FolderName } |
        Select-Object -First 1
    if (-not $folderItem) { throw "No se encontró la carpeta '$FolderName'." }

    $folder = $folderItem.GetFolder
    $result = @()
    foreach ($item in @($folder.Items())) {
        $name = [string]$item.Name
        if ($item.IsFolder -or $name -notmatch '\.(MOV|MP4|M4V|AVI|MKV|3GP)$') { continue }

        $result += [PSCustomObject]@{
            id       = New-FileId -FolderName $FolderName -FileName $name
            folder   = $FolderName
            name     = $name
            type     = [string]$item.Type
            size     = Get-ItemDetail -FolderObject $folder -ItemObject $item -Index 2
            modified = Get-ItemDetail -FolderObject $folder -ItemObject $item -Index 3
            created  = Get-ItemDetail -FolderObject $folder -ItemObject $item -Index 4
            duration = Get-ItemDetail -FolderObject $folder -ItemObject $item -Index 13
        }
    }
    return $result
}

try {
    $storage = Get-PhoneStorage

    if ($Action -eq 'folders') {
        $folders = @($storage.GetFolder.Items()) |
            Where-Object { $_.IsFolder } |
            ForEach-Object { [PSCustomObject]@{ name = [string]$_.Name } } |
            Sort-Object name -Descending
        @($folders) | ConvertTo-Json -Compress
        exit 0
    }

    if ($Action -eq 'files') {
        @(Get-VideoFiles -StorageItem $storage -FolderName $Folder) | ConvertTo-Json -Compress
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($Destination)) { throw 'No se indicó la carpeta de destino.' }
    $selections = @($SelectionsJson | ConvertFrom-Json)
    if ($selections.Count -eq 0) { throw 'No seleccionaste ningún vídeo.' }

    $destinationRoot = [IO.DirectoryInfo]$Destination
    if (-not $destinationRoot.Exists) { $destinationRoot.Create() }
    $shell = New-Object -ComObject Shell.Application
    $copied = @()
    $failed = @()

    foreach ($selection in $selections) {
        $folderName = [string]$selection.folder
        $fileName = [string]$selection.name
        if ($folderName -notmatch '^[-_A-Za-z0-9]+$' -or
            $fileName -match '[\\/:*?"<>|]' -or
            $fileName -notmatch '\.(MOV|MP4|M4V|AVI|MKV|3GP)$') {
            $failed += [PSCustomObject]@{ name = $fileName; error = 'Nombre no permitido.' }
            continue
        }

        $folderItem = @($storage.GetFolder.Items()) |
            Where-Object { $_.IsFolder -and $_.Name -eq $folderName } |
            Select-Object -First 1
        $sourceFolder = if ($folderItem) { $folderItem.GetFolder } else { $null }
        $sourceItem = if ($sourceFolder) {
            @($sourceFolder.Items()) | Where-Object { -not $_.IsFolder -and $_.Name -eq $fileName } | Select-Object -First 1
        } else { $null }

        if (-not $sourceItem) {
            $failed += [PSCustomObject]@{ name = "$folderName\$fileName"; error = 'No se encontró en el iPhone.' }
            continue
        }

        $targetDir = Join-Path $destinationRoot.FullName $folderName
        [IO.Directory]::CreateDirectory($targetDir) | Out-Null
        $targetFolder = $shell.NameSpace($targetDir)
        if (-not $targetFolder) {
            $failed += [PSCustomObject]@{ name = "$folderName\$fileName"; error = 'No se pudo abrir la carpeta de destino.' }
            continue
        }

        $targetPath = Join-Path $targetDir $fileName
        try {
            if (Test-Path -LiteralPath $targetPath) {
                $failed += [PSCustomObject]@{ name = "$folderName\$fileName"; error = 'Ya existe en la carpeta de destino; no se sobrescribió.' }
                continue
            }
            # 4=silencioso, 16=sin confirmación, 512=sin confirmar creación de carpetas,
            # 1024=sin interfaz de error.
            $targetFolder.CopyHere($sourceItem, 1556)
            $deadline = (Get-Date).AddMinutes(10)
            while (-not (Test-Path -LiteralPath $targetPath) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
            if (Test-Path -LiteralPath $targetPath) {
                $copied += [PSCustomObject]@{ name = "$folderName\$fileName"; path = $targetPath }
            } else {
                $failed += [PSCustomObject]@{ name = "$folderName\$fileName"; error = 'La copia no terminó dentro del tiempo esperado.' }
            }
        } catch {
            $failed += [PSCustomObject]@{ name = "$folderName\$fileName"; error = $_.Exception.Message }
        }
    }

    [PSCustomObject]@{ copied = @($copied); failed = @($failed); destination = $destinationRoot.FullName } | ConvertTo-Json -Compress -Depth 5
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
