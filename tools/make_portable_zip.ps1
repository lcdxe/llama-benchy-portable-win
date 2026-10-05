# Build the portable Release zip (the bundled runtime is NOT committed to git).

# Usage:
#   powershell -File tools/make_portable_zip.ps1
#   powershell -File tools/make_portable_zip.ps1 -RuntimeDir D:\path\to\python

# What goes in the zip:
#   - everything tracked by git (source, docs, launchers, data/book.txt, assets)
#   - the bundled runtime folder (python/) if it exists
# Excluded: .git, __pycache__, results/, .hf/, .tmp/, data/cache/, gui/runs/,
#           gui/batch.json, gui/gui.log, .venv/

param(
    [string]$RuntimeDir = "",
    [string]$OutFile = ""
)

$root = Split-Path -Parent $PSScriptRoot
$runtime = if ($RuntimeDir) { $RuntimeDir } else { Join-Path $root "python" }
$name = "llama-benchy-portable"
if (-not $OutFile) {
    $OutFile = Join-Path (Split-Path -Parent $root) "$name-win64.zip"
}

$excludeDirs = @("\.git\", "\__pycache__\", "\results\", "\.hf\", "\.tmp\", "\data\cache\", "\gui\runs\", "\.venv\")
$excludeFiles = @("gui/batch.json", "gui/gui.log", ".gitignore", ".gitattributes")

$staging = Join-Path $env:TEMP ("benchy_zip_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path (Join-Path $staging $name) -Force | Out-Null

function Copy-Tree($src, $dst) {
    Get-ChildItem -Recurse -File $src | Where-Object {
        $p = $_.FullName
        $skip = $false
        foreach ($x in $excludeDirs) { if ($p.Contains($x)) { $skip = $true; break } }
        foreach ($f in $excludeFiles) { if (($p -replace '\\', '/') -like "*$f") { $skip = $true; break } }
        -not $skip
    } | ForEach-Object {
        $rel = $_.FullName.Substring($src.Length).TrimStart('\')
        $target = Join-Path $dst $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item $_.FullName $target -Force
    }
}

Copy-Tree $root (Join-Path $staging $name)

if (Test-Path $runtime) {
    Copy-Tree $runtime (Join-Path $staging (Join-Path $name "python"))
    $runtimeNote = "runtime included: $runtime"
} else {
    $runtimeNote = "runtime NOT found ($runtime) - zip contains source only"
}

Compress-Archive -Path (Join-Path $staging $name) -DestinationPath $OutFile -CompressionLevel Optimal
Remove-Item -Recurse -Force $staging

"zip: $OutFile"
"size: {0:N1} MB" -f ((Get-Item $OutFile).Length / 1MB)
$runtimeNote
