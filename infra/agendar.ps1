# Agenda o vigia no Windows — sem VPS, sem servidor, sem custo.
#
# Sem agendamento, as teses são um museu: só são checadas se você lembrar de rodar o comando.
# Você não vai lembrar. Ninguém lembra.
#
#   Rode UMA vez, como administrador:   .\infra\agendar.ps1
#   Para remover:                       .\infra\agendar.ps1 -Remover

param([switch]$Remover)

$Nome = "Copiloto - vigia das teses"
$Raiz = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Raiz "backend\.venv\Scripts\dands.exe"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Vigia removido do agendador."
    exit
}

if (-not (Test-Path $Exe)) {
    Write-Host "ERRO: nao encontrei $Exe" -ForegroundColor Red
    Write-Host "Rode antes:  cd backend; python -m venv .venv; .venv\Scripts\pip install -e ."
    exit 1
}

# Diário às 20h: depois do fechamento da B3, e a CVM publica balanço ao longo do dia.
# O vigia é BARATO quando nada muda — ele checa e fica calado.
$Acao = New-ScheduledTaskAction -Execute $Exe -Argument "vigia" -WorkingDirectory (Join-Path $Raiz "backend")
$Gatilho = New-ScheduledTaskTrigger -Daily -At 20:00
$Config = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $Nome -Action $Acao -Trigger $Gatilho -Settings $Config -Force | Out-Null

Write-Host "Vigia agendado: todo dia as 20h." -ForegroundColor Green
Write-Host ""
Write-Host "  -StartWhenAvailable: se o PC estiver desligado as 20h, ele roda quando ligar."
Write-Host "  Sem isso, um dia desligado = um balanco perdido."
Write-Host ""
Write-Host "Configure o Telegram (backend\.env) para o alerta te ENCONTRAR:"
Write-Host "  TELEGRAM_TOKEN=...    TELEGRAM_CHAT_ID=..."
Write-Host ""
Write-Host "Testar agora:   Start-ScheduledTask -TaskName '$Nome'"
