[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$poolerPath = Join-Path $repositoryRoot "supabase\.temp\pooler-url"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $poolerPath -PathType Leaf)) {
    throw "Linked Supabase pooler metadata is missing. Run 'npx supabase link' first."
}
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "PFIS virtual environment is missing. Run the local setup first."
}

$poolerUri = [Uri](Get-Content -LiteralPath $poolerPath -Raw).Trim()
if (
    $poolerUri.Scheme -ne "postgresql" -or
    -not $poolerUri.Host -or
    $poolerUri.Port -lt 1 -or
    -not $poolerUri.UserInfo -or
    $poolerUri.UserInfo.Contains(":")
) {
    throw "Linked Supabase pooler metadata has an unexpected format."
}

$securePassword = Read-Host "Supabase database password" -AsSecureString
$plainPassword = [System.Net.NetworkCredential]::new("", $securePassword).Password
$encodedPassword = [Uri]::EscapeDataString($plainPassword)
$databaseName = $poolerUri.AbsolutePath.TrimStart("/")
if (-not $databaseName) {
    $databaseName = "postgres"
}

$databaseUrl = (
    "postgresql+asyncpg://{0}:{1}@{2}:{3}/{4}?ssl=require" -f
    $poolerUri.UserInfo,
    $encodedPassword,
    $poolerUri.Host,
    $poolerUri.Port,
    $databaseName
)

try {
    $env:DATABASE_URL = $databaseUrl
    Write-Host "[PFIS] Applying Alembic migrations to linked Supabase..."
    Push-Location (Join-Path $repositoryRoot "backend")
    try {
        & $pythonPath -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Hosted Alembic migration failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "[PFIS] Importing and verifying the retained legacy data..."
    & $pythonPath (Join-Path $repositoryRoot "scripts\migrate_sqlite_to_postgres.py") --apply
    if ($LASTEXITCODE -ne 0) {
        throw "Hosted legacy-data migration failed."
    }
    Write-Host "[PFIS] Hosted Supabase migration completed successfully."
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    $databaseUrl = $null
    $encodedPassword = $null
    $plainPassword = $null
    $securePassword = $null
}
