<#
.SYNOPSIS
    Script avanzado de gestión de energía con protecciones de:
    1. Rango Base (Prioridad absoluta de encendido).
    2. Ventana de protección Start (10 min antes/después).
    3. Prevalencia de Continuidad (No apaga si hay un Continuo-Stop posterior).
#>

Param(
    [Parameter(Mandatory=$false)]
    [String]$SubscriptionId = "b7e6c50a-3823-4d44-9f17-334c1abb7266",

    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop")]
    [String]$accion,

    [Parameter(Mandatory=$false)]
    [String]$resourceGroupName = "DefaultResourceGroup-EUS",

    [Parameter(Mandatory=$false)]
    [String]$automationAccountName = "automation-sch"
)

# 1. Autenticación e Inicialización
Write-Output "Autenticando en Azure..."
Connect-AzAccount -Identity
Set-AzContext -SubscriptionId $SubscriptionId
$now = Get-Date
Write-Output "Hora actual de ejecución: $($now.ToString('yyyy-MM-dd HH:mm:ss'))"

# ---------------------------------------------------------
# 2. VALIDACIÓN: ¿ESTAMOS EN RANGO DE PROGRAMACIÓN BASE?
# ---------------------------------------------------------
Write-Output "Verificando programación Base..."
$schBaseStart = Get-AzAutomationSchedule -ResourceGroupName $resourceGroupName -AutomationAccountName $automationAccountName -Name "Base_Start" -ErrorAction SilentlyContinue
$schBaseStop = Get-AzAutomationSchedule -ResourceGroupName $resourceGroupName -AutomationAccountName $automationAccountName -Name "Base_Stop" -ErrorAction SilentlyContinue

if ($schBaseStart -and $schBaseStop) {
    if ($schBaseStop.NextRun -lt $schBaseStart.NextRun) {
        Write-Output "No se ejecuta la acción de $(accion). El ambiente está en horario BASE. Se mantiene encendido."
        return 
    }
}

# ---------------------------------------------------------
# 3. VALIDACIONES ESPECÍFICAS PARA ACCIÓN: STOP
# ---------------------------------------------------------
if ($accion -eq "stop") {
    Write-Output "Evaluando reglas de protección para APAGADO..."
    $allSchedules = Get-AzAutomationSchedule -ResourceGroupName $resourceGroupName -AutomationAccountName $automationAccountName
    
    # --- REGLA A: PROTECCIÓN POR CONTINUIDAD FUTURA ---
    # Buscamos si hay algún stop de tipo "Continuo" programado para después de ahora
    # Usamos un margen de 2 minutos para evitar que el schedule actual se bloquee a sí mismo
    $ultimoContinuoStop = $allSchedules | Where-Object { 
        $_.Name -like "*Continuo-Stop*" -and 
        $_.IsEnabled -eq $true -and
        $_.NextRun -gt $now.AddMinutes(2) 
    } | Sort-Object NextRun -Descending | Select-Object -First 1

    if ($ultimoContinuoStop) {
        Write-Output "Existe una programación continua de $(accion) posterior: $($ultimoContinuoStop.Name) a las $($ultimoContinuoStop.NextRun)."
        Write-Output "El ambiente debe permanecer encendido hasta que se alcance el último stop continuo."
        return
    }

    # --- REGLA B: PROTECCIÓN START (VENTANA 10 MIN) ---
    $diezMinAntes = $now.AddMinutes(-10)
    $diezMinDespues = $now.AddMinutes(10)

    # ¿Viene un Start pronto?
    $proximoStart = $allSchedules | Where-Object { 
        $_.IsEnabled -eq $true -and $_.Name -like "*Start*" -and 
        $_.NextRun -gt $now -and $_.NextRun -lt $diezMinDespues 
    }

    # ¿Hubo un Start hace poco?
    $startReciente = $allSchedules | Where-Object { 
        $_.Name -like "*Start*" -and $_.LastRunTime -ne $null -and
        $_.LastRunTime -gt $diezMinAntes -and $_.LastRunTime -le $now
    }

    if ($proximoStart -or $startReciente) {
        Write-Output "No se ejecuta la acción de $(accion). Protección de 10 min activa. Se detectó un Start cercano (Pasado: $($startReciente.LastRunTime) o Futuro: $($proximoStart.NextRun))."
        return
    }
}

# ---------------------------------------------------------
# 4. EJECUCIÓN DE ACCIONES (Recursos)
# ---------------------------------------------------------
Write-Output "--- Iniciando ejecución de $accion ---"

# VM
$vms = Get-AzVM -ResourceGroupName $resourceGroupName
Write-Output "Ejecutando acción de $(accion) sobre las VM"
foreach ($vm in $vms) {
    if ($accion -eq "start") { Start-AzVM -ResourceGroupName $resourceGroupName -Name $vm.Name -NoWait }
    else { Stop-AzVM -ResourceGroupName $resourceGroupName -Name $vm.Name -Force -NoWait }
}

# AKS
$aksClusters = Get-AzAksCluster -ResourceGroupName $resourceGroupName
Write-Output "Ejecutando acción de $(accion) sobre los AKS"
foreach ($aks in $aksClusters) {
    if ($accion -eq "start") { Start-AzAksCluster -ResourceGroupName $resourceGroupName -Name $aks.Name -ErrorAction SilentlyContinue }
    else { Stop-AzAksCluster -ResourceGroupName $resourceGroupName -Name $aks.Name -ErrorAction SilentlyContinue }
}

# App Gateway
$appGws = Get-AzApplicationGateway -ResourceGroupName $resourceGroupName
Write-Output "Ejecutando acción de $(accion) sobre los Application Gateway"
foreach ($gw in $appGws) {
    if ($accion -eq "start") { Start-AzApplicationGateway -ApplicationGateway $gw }
    else { Stop-AzApplicationGateway -ApplicationGateway $gw }
}

Write-Output "--- Proceso de $accion finalizado con éxito ---"