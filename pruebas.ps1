# Corre TODAS las pruebas del proyecto con un solo comando, en PowerShell:   .\pruebas.ps1
# (si PowerShell bloquea el script:   powershell -ExecutionPolicy Bypass -File .\pruebas.ps1)
#
# Es el equivalente de pruebas.sh: mismas pruebas, mismo orden y mismo resultado. Si cambia la lista de servicios, hay que
# cambiarla en los dos archivos.
#
# Ejecuta, una tras otra, las unitarias y las de integracion de los tres servicios contra la base real del compose.
# Si un servicio falla, igual se corren los demas y el script termina con error. Termina con 0 solo si pasaron los tres.

Set-Location $PSScriptRoot   # que funcione desde cualquier carpeta

$fallidos = @()
foreach ($servicio in 'agenda', 'plataforma', 'auditoria') {
    Write-Host ""
    Write-Host "=============== pruebas de $servicio ==============="
    # --build: que las pruebas usen el codigo actual. -T: sin terminal interactiva, para que corra tambien en un script o CI.
    docker compose --profile pruebas run --rm --build -T "pruebas-$servicio"
    if ($LASTEXITCODE -ne 0) { $fallidos += $servicio }
}

Write-Host ""
Write-Host "=============== resumen ==============="
if ($fallidos.Count -gt 0) {
    Write-Host "FALLARON las pruebas de: $($fallidos -join ' ')"
    exit 1
}
Write-Host "Pasaron las pruebas de los tres servicios (agenda, plataforma y auditoria)."
