param(
    [string]$ProjectRoot = "C:\Users\huang\Desktop\money_trade",
    [string]$ProjectId = "select-stock-list",
    [string]$Region = "asia-east1",
    [string]$ServiceName = "money-trade-line-push"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$EnvFile = Join-Path $ProjectRoot ".env"
$SourceDir = Join-Path $ProjectRoot "cloud_line"
$GcloudCandidates = @(
    (Get-Command gcloud -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
    (Join-Path $env:ProgramFiles "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$Gcloud = $GcloudCandidates | Select-Object -First 1

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env not found: $Path"
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $name, $value = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim().Trim('"').Trim("'"), "Process")
    }
}

function Set-DotEnvValue {
    param([string]$Path, [string]$Name, [string]$Value)
    $lines = if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path -Encoding UTF8) } else { @() }
    $updated = $false
    $newLines = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Name))=") {
            "$Name=$Value"
            $updated = $true
        }
        else {
            $line
        }
    }
    if (-not $updated) {
        $newLines += "$Name=$Value"
    }
    Set-Content -LiteralPath $Path -Value $newLines -Encoding UTF8
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Set-GcpSecret {
    param([string]$Name, [string]$Value)
    $exists = @(
        & $Gcloud secrets list `
            --project $env:GCP_PROJECT_ID `
            --format="value(name)"
    ) -contains $Name
    if (-not $exists) {
        & $Gcloud secrets create $Name --project $env:GCP_PROJECT_ID --replication-policy="automatic" | Out-Null
    }
    $tempFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tempFile, $Value, [System.Text.UTF8Encoding]::new($false))
        & $Gcloud secrets versions add $Name --project $env:GCP_PROJECT_ID --data-file=$tempFile | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
    $versions = @(
        & $Gcloud secrets versions list $Name `
            --project $env:GCP_PROJECT_ID `
            --filter="state!=DESTROYED" `
            --sort-by="~createTime" `
            --format="value(name.basename())"
    )
    $versions | Select-Object -Skip 1 | ForEach-Object {
        & $Gcloud secrets versions destroy $_ --secret=$Name --project $env:GCP_PROJECT_ID --quiet | Out-Null
    }
}

function Initialize-GcpSecret {
    param([string]$Name, [string]$Value)
    $exists = @(
        & $Gcloud secrets list `
            --project $env:GCP_PROJECT_ID `
            --format="value(name)"
    ) -contains $Name
    if (-not $exists) {
        & $Gcloud secrets create $Name --project $env:GCP_PROJECT_ID --replication-policy="automatic" | Out-Null
        $tempFile = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllText($tempFile, $Value, [System.Text.UTF8Encoding]::new($false))
            & $Gcloud secrets versions add $Name --project $env:GCP_PROJECT_ID --data-file=$tempFile | Out-Null
        }
        finally {
            Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $Gcloud) {
    throw "Google Cloud CLI (gcloud) is not installed. Install it, run 'gcloud auth login', then rerun this script."
}

Import-DotEnv $EnvFile
[Environment]::SetEnvironmentVariable("GCP_PROJECT_ID", $ProjectId, "Process")

foreach ($name in @("LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET", "LINE_TARGET_ID")) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
        throw "Missing $name in .env"
    }
}

if ([string]::IsNullOrWhiteSpace($env:LINE_CLOUD_PUSH_KEY)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $pushKey = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    Set-DotEnvValue -Path $EnvFile -Name "LINE_CLOUD_PUSH_KEY" -Value $pushKey
}

& $Gcloud config set project $env:GCP_PROJECT_ID | Out-Null
& $Gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com --project $env:GCP_PROJECT_ID

Set-GcpSecret -Name "money-trade-line-token" -Value $env:LINE_CHANNEL_ACCESS_TOKEN
Set-GcpSecret -Name "money-trade-line-channel-secret" -Value $env:LINE_CHANNEL_SECRET
Initialize-GcpSecret -Name "money-trade-line-target" -Value $env:LINE_TARGET_ID
Set-GcpSecret -Name "money-trade-push-key" -Value $env:LINE_CLOUD_PUSH_KEY

& $Gcloud run deploy $ServiceName `
    --project $env:GCP_PROJECT_ID `
    --region $Region `
    --source $SourceDir `
    --allow-unauthenticated `
    --min-instances 0 `
    --max-instances 1 `
    --no-cpu-boost `
    --cpu-throttling `
    --memory 256Mi `
    --cpu 1 `
    --set-env-vars "GCP_PROJECT_ID=$ProjectId" `
    --set-secrets "LINE_CHANNEL_ACCESS_TOKEN=money-trade-line-token:latest,LINE_CHANNEL_SECRET=money-trade-line-channel-secret:latest,LINE_CLOUD_PUSH_KEY=money-trade-push-key:latest"

$serviceUrl = & $Gcloud run services describe $ServiceName `
    --project $env:GCP_PROJECT_ID `
    --region $Region `
    --format="value(status.url)"

if ([string]::IsNullOrWhiteSpace($serviceUrl)) {
    throw "Cloud Run deployed but service URL could not be read."
}

Set-DotEnvValue -Path $EnvFile -Name "LINE_CLOUD_PUSH_URL" -Value $serviceUrl
Set-DotEnvValue -Path $EnvFile -Name "GCP_PROJECT_ID" -Value $ProjectId

Write-Host "Cloud Run deployment completed."
Write-Host "Service URL: $serviceUrl"
Write-Host "Test with: python scripts\send_line_holdings.py"
