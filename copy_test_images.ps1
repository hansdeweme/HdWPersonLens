$Source      = "E:\persons_dataset_test_selection"
$Destination = "E:\persons_unknown"

$ImageExtensions = @(
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".gif", ".tif", ".tiff",
    ".heic", ".heif"
)

New-Item -ItemType Directory -Path $Destination -Force | Out-Null

$CopiedCount = 0

Get-ChildItem -LiteralPath $Source -Recurse -File |
    Where-Object {
        $ImageExtensions -contains $_.Extension.ToLowerInvariant()
    } |
    ForEach-Object {
        # Include the relative source path in the filename, preventing collisions.
        $RelativePath = $_.FullName.Substring($Source.Length).TrimStart("\")
        $SafeName = $RelativePath -replace '[\\/:*?"<>|]', "__"

        $TargetPath = Join-Path $Destination $SafeName

        # Additional safeguard in case the resulting name still exists.
        if (Test-Path -LiteralPath $TargetPath) {
            $BaseName = [System.IO.Path]::GetFileNameWithoutExtension($SafeName)
            $Extension = [System.IO.Path]::GetExtension($SafeName)
            $Number = 2

            do {
                $TargetPath = Join-Path $Destination "${BaseName}_${Number}${Extension}"
                $Number++
            }
            while (Test-Path -LiteralPath $TargetPath)
        }

        Copy-Item -LiteralPath $_.FullName -Destination $TargetPath
        $CopiedCount++
    }

Write-Host "Copied $CopiedCount image files to $Destination"