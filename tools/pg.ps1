<#
.SYNOPSIS
  Start, stop or check the local PostgreSQL 17 server for the DSR database.

.DESCRIPTION
  PostgreSQL is installed at C:\Users\Praneet\pgsql17 as a plain binary
  distribution rather than through the EnterpriseDB installer, because the
  EnterpriseDB CDN is blocked on this network. That means there is no Windows
  service registered, so the server is started and stopped by hand with this
  script.

  To have it start with Windows instead, run PowerShell as Administrator:
      & "C:\Users\Praneet\pgsql17\bin\pg_ctl.exe" register -N postgresql-17 `
          -D "C:\Users\Praneet\pgsql17\data" -o "-p 5432"
      Start-Service postgresql-17

.EXAMPLE
  .\tools\pg.ps1 start
  .\tools\pg.ps1 status
  .\tools\pg.ps1 stop
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "log")]
    [string]$Action = "status"
)

$PgRoot = "C:\Users\Praneet\pgsql17"
$PgCtl  = Join-Path $PgRoot "bin\pg_ctl.exe"
$DataDir = Join-Path $PgRoot "data"
$LogFile = Join-Path $PgRoot "server.log"

if (-not (Test-Path $PgCtl)) {
    Write-Error "pg_ctl not found at $PgCtl - is PostgreSQL installed?"
    exit 1
}

switch ($Action) {
    "start" {
        # -w waits until the server is actually accepting connections, so a
        # following psql or ETL run cannot race the startup.
        & $PgCtl -D $DataDir -l $LogFile -o "-p 5432" -w start
    }
    "stop" {
        & $PgCtl -D $DataDir -m fast -w stop
    }
    "restart" {
        & $PgCtl -D $DataDir -l $LogFile -o "-p 5432" -m fast -w restart
    }
    "status" {
        & $PgCtl -D $DataDir status
        $reachable = Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($reachable) {
            Write-Host "port 5432: accepting connections" -ForegroundColor Green
        } else {
            Write-Host "port 5432: not listening" -ForegroundColor Yellow
        }
    }
    "log" {
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 40 }
        else { Write-Host "no log yet at $LogFile" }
    }
}
