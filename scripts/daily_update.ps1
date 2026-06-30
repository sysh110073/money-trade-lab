param(
    [string]$ProjectRoot = "C:\Users\huang\Desktop\money_trade",
    [string]$ConfigPath = "trading_code_ml\config\production.yaml",
    [string]$FundamentalAnalysisRoot = "C:\Users\huang\Desktop\Fundamental Analysis",
    [string]$ProcessedFeaturesPath = "",
    [string]$EndDate = "",
    [switch]$SkipApiFetch,
    [switch]$SkipBacktest,
    [switch]$SkipSentiment,
    [switch]$SkipBuild,
    [switch]$SkipHealthCheck,
    [switch]$SkipLineNotify,
    [switch]$SkipFundamentalSync
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($EndDate)) {
    $EndDate = Get-Date -Format "yyyy-MM-dd"
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$Python = "python"
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot $ConfigPath
}
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path

function Get-ConfigValue {
    param(
        [string]$Key,
        [string]$Default = ""
    )
    $value = & $Python (Join-Path $ProjectRoot "scripts\config_value.py") $ConfigPath $Key
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value.Trim()
}

function Resolve-ConfiguredPath {
    param(
        [string]$Value,
        [string]$Default
    )
    $pathValue = if ([string]::IsNullOrWhiteSpace($Value)) { $Default } else { $Value }
    if ([System.IO.Path]::IsPathRooted($pathValue)) {
        return $pathValue
    }
    return Join-Path $ProjectRoot $pathValue
}

$ProcessedConfigPath = if ([string]::IsNullOrWhiteSpace($ProcessedFeaturesPath)) {
    Get-ConfigValue "paths.processed_features"
}
else {
    $ProcessedFeaturesPath
}
$ProcessedFeaturesPath = Resolve-ConfiguredPath `
    -Value $ProcessedConfigPath `
    -Default (Join-Path $ProjectRoot "data\processed\all_features.csv")
$RawDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.raw_dir") (Join-Path $ProjectRoot "data\raw")
$OfficialRankDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.official_rank_dir") (Join-Path $ProjectRoot "trading_code_ml\results\rank_portfolio_optimized_risk_long_20pct_norebalance")
$ForwardSimDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.forward_sim_dir") (Join-Path $ProjectRoot "trading_code_ml\results\forward_simulation")
$DataUpdateDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.data_update_dir") (Join-Path $ProjectRoot "trading_code_ml\results\data_update")
$FrontDataDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.frontend_data_dir") (Join-Path $ProjectRoot "frontend\src\data")
$DataHealthDir = Resolve-ConfiguredPath (Get-ConfigValue "paths.data_health_dir") (Join-Path $ProjectRoot "logs\data_health")
$SqliteDb = Resolve-ConfiguredPath (Get-ConfigValue "paths.sqlite_db") (Join-Path $ProjectRoot "data\market_data.db")

$OfficialRunName = Get-ConfigValue "production.official_run_name" "official_rank_portfolio"
$ForwardRunName = Get-ConfigValue "production.forward_run_name" "forward_sim_20260605_1m"
$Capital = Get-ConfigValue "portfolio.initial_capital" "1000000"
$TargetExposure = Get-ConfigValue "portfolio.target_exposure" "1.0"
$PortfolioMaxPositions = Get-ConfigValue "portfolio.max_positions" "8"
$PortfolioMaxPositionPct = Get-ConfigValue "portfolio.max_position_pct" "0.20"
$PositionSizing = Get-ConfigValue "portfolio.position_sizing" "risk_parity"
$MaxRiskPerTrade = Get-ConfigValue "portfolio.max_risk_per_trade" "0.02"
$MinTradeUnit = Get-ConfigValue "trading.min_trade_unit" "1000"
$HoldingPeriodMax = Get-ConfigValue "risk.max_holding_days" "180"
$ForwardStartDate = Get-ConfigValue "daily.forward_start_date" "2026-06-05"
$TrailingStopSellPct = Get-ConfigValue "daily.trailing_stop_sell_pct" "0.5"
$AllowedSignalRegimes = Get-ConfigValue "strategy.allowed_signal_regimes" "bull,neutral,recovery"
$TopN = Get-ConfigValue "strategy.top_n" "12"
$MinScore = Get-ConfigValue "strategy.min_strategy_score" "0.62"
$MinMarketBreadthMa20 = Get-ConfigValue "risk.min_market_breadth_ma20" "0.42"
$MinMarketPositiveReturn5 = Get-ConfigValue "risk.min_market_positive_return_5" "0.22"
$MaxMarketVolatility20 = Get-ConfigValue "risk.max_market_volatility_20" "0.055"
$AtrStopMultiplier = Get-ConfigValue "risk.atr_stop_multiplier" "5.0"
$TakeProfitPct = Get-ConfigValue "risk.take_profit_pct" "1.0"
$TrailingStopTrigger = Get-ConfigValue "risk.trailing_stop_trigger" "0.30"
$TrailingStopAtr = Get-ConfigValue "risk.trailing_stop_atr" "3.5"
$MaxEntryVolumePct = Get-ConfigValue "execution.max_entry_volume_pct" "0.01"
$MaxEntryNotional = Get-ConfigValue "execution.max_entry_notional" "2000000"
$MarketImpactSlippage = Get-ConfigValue "execution.market_impact_slippage" "0.10"
$ReplacementThreshold = Get-ConfigValue "execution.replacement_threshold" "0.05"
$ReplacementCostScoreScale = Get-ConfigValue "execution.replacement_cost_score_scale" "10.0"

$LogDir = Join-Path $ProjectRoot "logs\daily_update"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "daily_update_$Stamp.log"
$RunId = "{0}_{1}_prod" -f ($EndDate -replace "-", ""), $Stamp
$RunDir = Join-Path $ProjectRoot (Join-Path "runs\$EndDate" $RunId)
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$ManifestPath = Join-Path $RunDir "run_manifest.json"
$TaskStatusPath = Join-Path $RunDir "task_status.json"
$LineMarkerPath = Join-Path $RunDir "line_notification.json"
$ConfigHash = "sha256:$((Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash.ToLower())"
$GitCommit = (& git -C $ProjectRoot rev-parse HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($GitCommit)) { $GitCommit = "unknown" }
$FeatureDataHash = if (Test-Path -LiteralPath $ProcessedFeaturesPath) {
    "sha256:$((Get-FileHash -LiteralPath $ProcessedFeaturesPath -Algorithm SHA256).Hash.ToLower())"
}
else {
    $null
}
$UniverseFile = Join-Path $ProjectRoot "stock_universe\selected_stocks_500_liquid.csv"
$UniverseVersion = if (Test-Path -LiteralPath $UniverseFile) {
    "selected_stocks_500_liquid:$((Get-FileHash -LiteralPath $UniverseFile -Algorithm SHA256).Hash.ToLower())"
}
else {
    "unknown"
}
$ExecutionDate = ([datetime]::Parse($EndDate)).AddDays(1).ToString("yyyy-MM-dd")

$script:RunStatus = "started"
$script:RunError = $null
$script:HealthStatus = if ($SkipHealthCheck) { "SKIPPED" } else { "PENDING" }
$script:HealthReport = $null
$script:ApiFetchStatus = if ($SkipApiFetch) { "SKIPPED" } else { "PENDING" }
$script:RankStatus = if ($SkipBacktest) { "SKIPPED" } else { "PENDING" }
$script:ForwardStatus = if ($SkipBacktest) { "SKIPPED" } else { "PENDING" }
$script:FrontendDataStatus = "PENDING"
$script:SentimentStatus = if ($SkipSentiment) { "SKIPPED" } else { "PENDING" }
$script:BuildStatus = if ($SkipBuild) { "SKIPPED" } else { "PENDING" }
$script:SqliteFeaturesStatus = "PENDING"
$script:SqliteOfficialStatus = "PENDING"
$script:SqliteForwardStatus = "PENDING"
$script:LineNotifyStatus = if ($SkipLineNotify) { "SKIPPED" } else { "PENDING" }
$script:FundamentalSyncStatus = if ($SkipFundamentalSync) { "SKIPPED" } else { "PENDING" }
$script:TaskRecords = @()

function Write-Step {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Existing-Or-Planned {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return (Resolve-Path -LiteralPath $Path).Path
    }
    return $Path
}

function Write-TaskStatus {
    $payload = [ordered]@{
        run_id = $RunId
        generated_at = (Get-Date).ToString("o")
        tasks = $script:TaskRecords
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $TaskStatusPath -Encoding UTF8
}

function Write-Manifest {
    $manifest = [ordered]@{
        run_id = $RunId
        run_type = "production"
        as_of_date = $EndDate
        expected_date = $EndDate
        execution_date = $ExecutionDate
        signal_available_at = (Get-Date).ToString("o")
        generated_at = (Get-Date).ToString("o")
        status = $script:RunStatus
        error = $script:RunError
        config_file = $ConfigPath
        config_hash = $ConfigHash
        git_commit = $GitCommit.Trim()
        universe_version = $UniverseVersion
        feature_data_hash = $FeatureDataHash
        price_source = Get-ConfigValue "data.source" "unknown"
        institutional_source = "twse_t86_tpex"
        strategy_version = $OfficialRunName
        result_directory = Existing-Or-Planned $OfficialRankDir
        health_gate = $script:HealthStatus
        official_run_name = $OfficialRunName
        forward_run_name = $ForwardRunName
        task_status_file = Existing-Or-Planned $TaskStatusPath
        steps = [ordered]@{
            api_fetch = $script:ApiFetchStatus
            official_rank = $script:RankStatus
            forward_sim = $script:ForwardStatus
            frontend_data = $script:FrontendDataStatus
            sentiment_data = $script:SentimentStatus
            frontend_build = $script:BuildStatus
            sqlite_features_import = $script:SqliteFeaturesStatus
            sqlite_official_import = $script:SqliteOfficialStatus
            sqlite_forward_import = $script:SqliteForwardStatus
            line_notify = $script:LineNotifyStatus
            fundamental_sync = $script:FundamentalSyncStatus
        }
        artifacts = [ordered]@{
            official_rank_dir = Existing-Or-Planned $OfficialRankDir
            forward_sim_dir = Existing-Or-Planned $ForwardSimDir
            frontend_data_dir = Existing-Or-Planned $FrontDataDir
            sqlite_db = Existing-Or-Planned $SqliteDb
            data_health_report = $script:HealthReport
            log_file = Existing-Or-Planned $LogFile
        }
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
}

trap {
    if ($script:HealthStatus -eq "RUNNING") {
        $script:HealthStatus = "FAIL"
        if (Test-Path -LiteralPath $DataHealthDir) {
            $latestHealth = Get-ChildItem -LiteralPath $DataHealthDir -Filter "data_health_*.json" |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            $script:HealthReport = if ($latestHealth) { $latestHealth.FullName } else { $script:HealthReport }
        }
    }
    foreach ($name in @(
        "ApiFetchStatus",
        "RankStatus",
        "ForwardStatus",
        "FrontendDataStatus",
        "SentimentStatus",
        "BuildStatus",
        "SqliteFeaturesStatus",
        "SqliteOfficialStatus",
        "SqliteForwardStatus",
        "LineNotifyStatus",
        "FundamentalSyncStatus"
    )) {
        if ((Get-Variable -Name $name -Scope Script -ValueOnly) -eq "RUNNING") {
            Set-Variable -Name $name -Scope Script -Value "FAIL"
        }
    }
    foreach ($record in $script:TaskRecords) {
        if ($record["status"] -eq "running") {
            $record["status"] = "failed"
            $record["finished_at"] = (Get-Date).ToString("o")
            $record["error_message"] = $_.Exception.Message
        }
    }
    $script:RunStatus = "failed"
    $script:RunError = $_.Exception.Message
    if (Get-Command Write-Step -ErrorAction SilentlyContinue) {
        Write-Step "FAILED $script:RunError"
    }
    Write-TaskStatus
    Write-Manifest
    throw
}

function Invoke-Logged {
    param(
        [string]$Title,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot
    )
    Write-Step "START $Title"
    $SafeTitle = ($Title -replace '[^a-zA-Z0-9_-]', '_')
    $StdOut = Join-Path $LogDir "$Stamp`_$SafeTitle.out.log"
    $StdErr = Join-Path $LogDir "$Stamp`_$SafeTitle.err.log"
    $task = [ordered]@{
        task_name = $SafeTitle
        title = $Title
        status = "running"
        attempt = 1
        started_at = (Get-Date).ToString("o")
        finished_at = $null
        exit_code = $null
        input_hash = $ConfigHash
        output_hash = $null
        error_message = $null
        stdout = $StdOut
        stderr = $StdErr
    }
    $script:TaskRecords += $task
    Write-TaskStatus
    Push-Location $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 1> $StdOut 2> $StdErr
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    $stdoutText = if (Test-Path -LiteralPath $StdOut) { Get-Content -LiteralPath $StdOut -Raw -Encoding UTF8 } else { "" }
    $stderrText = if (Test-Path -LiteralPath $StdErr) { Get-Content -LiteralPath $StdErr -Raw -Encoding UTF8 } else { "" }

    if ($stdoutText) {
        Set-Content -LiteralPath $StdOut -Value $stdoutText -Encoding UTF8
        $stdoutText.TrimEnd() -split "`r?`n" | Tee-Object -FilePath $LogFile -Append
    }
    if ($stderrText) {
        Set-Content -LiteralPath $StdErr -Value $stderrText -Encoding UTF8
        $stderrLines = $stderrText.TrimEnd() -split "`r?`n"
        if ($stderrLines) {
            Write-Step "STDERR from $Title"
            $stderrLines | Tee-Object -FilePath $LogFile -Append
        }
    }
    if ($exitCode -ne 0) {
        $task["status"] = "failed"
        $task["finished_at"] = (Get-Date).ToString("o")
        $task["exit_code"] = $exitCode
        $task["error_message"] = "$Title failed with exit code $exitCode"
        Write-TaskStatus
        throw "$Title failed with exit code $exitCode"
    }
    $task["status"] = "success"
    $task["finished_at"] = (Get-Date).ToString("o")
    $task["exit_code"] = $exitCode
    Write-TaskStatus
    Write-Step "DONE $Title"
}

$FrontendDir = Join-Path $ProjectRoot "frontend"
$NpmLocal = Join-Path $FrontendDir "npm-local.cmd"

Write-Step "Daily update started. run_id=$RunId end_date=$EndDate config=$ConfigPath"
Write-Manifest

if (-not $SkipApiFetch) {
    $script:ApiFetchStatus = "RUNNING"
    Invoke-Logged -Title "Fetch latest API data and rebuild features" -FilePath $Python -Arguments @(
        "trading_code_ml\scripts\update_latest_features.py",
        "--config", $ConfigPath,
        "--processed", $ProcessedFeaturesPath,
        "--output", $ProcessedFeaturesPath,
        "--raw-dir", $RawDir,
        "--output-dir", $DataUpdateDir,
        "--end-date", $EndDate
    )
    $script:ApiFetchStatus = "PASS"
}
else {
    Write-Step "SKIP API fetch"
}

if (-not $SkipBacktest) {
    $rankCommonArgs = @(
        "trading_code_ml\scripts\run_rank_portfolio_backtest.py",
        "--config", $ConfigPath,
        "--data", $ProcessedFeaturesPath,
        "--capital", $Capital,
        "--target-exposure", $TargetExposure,
        "--portfolio-max-positions", $PortfolioMaxPositions,
        "--portfolio-max-position-pct", $PortfolioMaxPositionPct,
        "--position-sizing", $PositionSizing,
        "--max-risk-per-trade", $MaxRiskPerTrade,
        "--min-trade-unit", $MinTradeUnit,
        "--holding-period-max", $HoldingPeriodMax,
        "--top-n", $TopN,
        "--min-score", $MinScore,
        "--allowed-signal-regimes", $AllowedSignalRegimes,
        "--min-market-breadth-ma20", $MinMarketBreadthMa20,
        "--min-market-positive-return-5", $MinMarketPositiveReturn5,
        "--max-market-volatility-20", $MaxMarketVolatility20,
        "--atr-stop-multiplier", $AtrStopMultiplier,
        "--take-profit-pct", $TakeProfitPct,
        "--trailing-stop-trigger", $TrailingStopTrigger,
        "--trailing-stop-atr", $TrailingStopAtr,
        "--trailing-stop-sell-pct", $TrailingStopSellPct,
        "--max-entry-volume-pct", $MaxEntryVolumePct,
        "--max-entry-notional", $MaxEntryNotional,
        "--market-impact-slippage", $MarketImpactSlippage,
        "--replacement-threshold", $ReplacementThreshold,
        "--replacement-cost-score-scale", $ReplacementCostScoreScale
    )
    $rankArgs = $rankCommonArgs + @("--output-dir", $OfficialRankDir)
    $script:RankStatus = "RUNNING"
    Invoke-Logged -Title "Refresh official Risk Parity Best portfolio outputs" -FilePath $Python -Arguments $rankArgs
    $script:RankStatus = "PASS"

    $forwardArgs = $rankCommonArgs + @(
        "--simulation-start-date", $ForwardStartDate,
        "--output-dir", $ForwardSimDir
    )
    $script:ForwardStatus = "RUNNING"
    Invoke-Logged -Title "Run 1M Capital Forward Simulation" -FilePath $Python -Arguments $forwardArgs
    $script:ForwardStatus = "PASS"
}
else {
    Write-Step "SKIP backtest"
}

$script:FrontendDataStatus = "RUNNING"
Invoke-Logged -Title "Refresh dashboard data" -FilePath $Python -Arguments @(
    "frontend\scripts\generate_dashboard_data.py",
    "--config", $ConfigPath,
    "--processed", $ProcessedFeaturesPath,
    "--official-rank-dir", $OfficialRankDir,
    "--forward-sim-dir", $ForwardSimDir,
    "--front-data", $FrontDataDir,
    "--run-id", $RunId,
    "--config-hash", $ConfigHash,
    "--strategy-version", $OfficialRunName
)
$script:FrontendDataStatus = "PASS"

if (-not $SkipSentiment) {
    $script:SentimentStatus = "RUNNING"
    Invoke-Logged -Title "Refresh sentiment dashboard data" -FilePath $Python -Arguments @("frontend\scripts\generate_sentiment_data.py")
    $script:SentimentStatus = "PASS"
}
else {
    Write-Step "SKIP sentiment"
}

if (-not $SkipBuild) {
    $script:BuildStatus = "RUNNING"
    Invoke-Logged -Title "Build React dashboard" -FilePath $NpmLocal -Arguments @("run", "build") -WorkingDirectory $FrontendDir
    $script:BuildStatus = "PASS"
}
else {
    Write-Step "SKIP frontend build"
}

if (-not $SkipHealthCheck) {
    $script:HealthStatus = "RUNNING"
    $healthArgs = @(
        "scripts\check_data_health.py",
        "--expected-date", $EndDate,
        "--processed", $ProcessedFeaturesPath,
        "--rank-dir", $OfficialRankDir,
        "--data-update-dir", $DataUpdateDir,
        "--front-data", $FrontDataDir,
        "--output-dir", $DataHealthDir,
        "--run-id", $RunId,
        "--config-hash", $ConfigHash
    )
    if ($SkipSentiment) {
        $healthArgs += "--skip-sentiment-generated-today"
    }
    Invoke-Logged -Title "Run daily data health check" -FilePath $Python -Arguments $healthArgs
    $latestHealth = Get-ChildItem -LiteralPath $DataHealthDir -Filter "data_health_*.json" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $script:HealthStatus = "PASS"
    $script:HealthReport = if ($latestHealth) { $latestHealth.FullName } else { $null }
}
else {
    Write-Step "SKIP data health check"
}

Write-Step "Syncing data to SQLite database..."
$script:SqliteFeaturesStatus = "RUNNING"
Invoke-Logged -Title "Sync SQLite Database Features" -FilePath $Python -Arguments @(
    "scripts\db_importer.py",
    "--import-features", $ProcessedFeaturesPath
)
$script:SqliteFeaturesStatus = "PASS"

$latestSummary = Join-Path $OfficialRankDir "rank_portfolio_summary.json"
if (Test-Path -LiteralPath $latestSummary) {
    $script:SqliteOfficialStatus = "RUNNING"
    Invoke-Logged -Title "Sync SQLite Database Backtest Run" -FilePath $Python -Arguments @(
        "scripts\db_importer.py",
        "--import-backtest", $OfficialRunName,
        "--run-uid", $RunId,
        "--config-hash", $ConfigHash,
        "--summary", $latestSummary,
        "--trades", (Join-Path $OfficialRankDir "rank_portfolio_trades.csv"),
        "--equity", (Join-Path $OfficialRankDir "rank_portfolio_equity.csv"),
        "--positions", (Join-Path $OfficialRankDir "rank_portfolio_positions.csv"),
        "--buys", (Join-Path $OfficialRankDir "rank_portfolio_buys.csv")
    )
    $script:SqliteOfficialStatus = "PASS"
}
else {
    $script:SqliteOfficialStatus = "SKIPPED_NO_SUMMARY"
}

$forwardSummary = Join-Path $ForwardSimDir "rank_portfolio_summary.json"
if (Test-Path -LiteralPath $forwardSummary) {
    $script:SqliteForwardStatus = "RUNNING"
    Invoke-Logged -Title "Sync SQLite Database Forward Simulation" -FilePath $Python -Arguments @(
        "scripts\db_importer.py",
        "--import-backtest", $ForwardRunName,
        "--run-uid", $RunId,
        "--config-hash", $ConfigHash,
        "--summary", $forwardSummary,
        "--trades", (Join-Path $ForwardSimDir "rank_portfolio_trades.csv"),
        "--equity", (Join-Path $ForwardSimDir "rank_portfolio_equity.csv"),
        "--positions", (Join-Path $ForwardSimDir "rank_portfolio_positions.csv"),
        "--buys", (Join-Path $ForwardSimDir "rank_portfolio_buys.csv")
    )
    $script:SqliteForwardStatus = "PASS"
}
else {
    $script:SqliteForwardStatus = "SKIPPED_NO_SUMMARY"
}

if (-not $SkipLineNotify) {
    $script:LineNotifyStatus = "RUNNING"
    Invoke-Logged -Title "Send strategy holdings to LINE" -FilePath $Python -Arguments @(
        "scripts\send_line_holdings.py",
        "--expected-date", $EndDate,
        "--run-id", $RunId,
        "--notification-marker", $LineMarkerPath
    )
    $script:LineNotifyStatus = "PASS"
}
else {
    Write-Step "SKIP LINE notification"
}

if (-not $SkipFundamentalSync) {
    $FundamentalSyncScript = Join-Path $FundamentalAnalysisRoot "scripts\sync_watchlist_research.ps1"
    if (Test-Path -LiteralPath $FundamentalSyncScript) {
        $script:FundamentalSyncStatus = "RUNNING"
        Invoke-Logged `
            -Title "Sync Fundamental Lens watchlist and company research" `
            -FilePath "powershell.exe" `
            -Arguments @(
                "-ExecutionPolicy", "Bypass",
                "-File", $FundamentalSyncScript
            ) `
            -WorkingDirectory $FundamentalAnalysisRoot
        $script:FundamentalSyncStatus = "PASS"
    }
    else {
        $script:FundamentalSyncStatus = "SKIPPED_SCRIPT_MISSING"
        Write-Step "SKIP Fundamental Lens sync: script not found at $FundamentalSyncScript"
    }
}
else {
    Write-Step "SKIP Fundamental Lens sync"
}

$script:RunStatus = "pass"
Write-Manifest
Write-Step "Daily update finished."
Write-Step "Run manifest: $ManifestPath"
Write-Step "Log file: $LogFile"
