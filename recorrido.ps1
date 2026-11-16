# Recorrido de una cita contra la API real, de punta a punta, para la demostracion:   .\recorrido.ps1
#   -Pausar   espera un Enter entre pasos (para narrar en vivo)       -Base   otra direccion del gateway
#
# Muestra, paso a paso y con el codigo HTTP de cada uno: reservar (RF9), el mismo espacio otra vez (409, I1), que el espacio
# ya no se ofrece (I8), que no se puede dar el desenlace antes de la hora (422), reprogramar (RF10), cancelar (RF11), cancelar
# una cancelada (409, RF13) y, sobre una cita ya pasada de la semilla, el desenlace ATENDIDA (RF12) y su repeticion (409).
#
# Requiere el sistema levantado (docker compose up -d) y los usuarios de prueba de Keycloak. Cada corrida deja citas
# canceladas y consume UNA cita pasada de la semilla (queda ATENDIDA); con `docker compose down -v` se vuelve al inicio.
# Termina con codigo 1 si algun paso no devuelve lo esperado, asi que tambien sirve de prueba de humo.
# (Escrito sin tildes en los textos: Windows PowerShell 5.1 lee mal el UTF-8 sin BOM. Probado en 5.1.)

param([string]$Base = 'http://localhost:8080', [switch]$Pausar)
$Base = $Base.TrimEnd('/')
$fallos = @()

function Json($texto) {
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        # En PowerShell 7 las fechas ISO se convierten a DateTime y se perderia el formato exacto que la API espera de vuelta.
        try { return $texto | ConvertFrom-Json -DateKind String } catch { }
    }
    return $texto | ConvertFrom-Json
}

function Pedir($metodo, $ruta, $token = $null, $cuerpo = $null, $form = $null) {
    $p = @{ Uri = $Base + $ruta; Method = $metodo; UseBasicParsing = $true }
    if ($token) { $p.Headers = @{ Authorization = "Bearer $token" } }
    if ($null -ne $cuerpo) {
        $p.Body = [Text.Encoding]::UTF8.GetBytes(($cuerpo | ConvertTo-Json -Compress))
        $p.ContentType = 'application/json; charset=utf-8'
    }
    if ($null -ne $form) { $p.Body = $form }
    try {
        $r = Invoke-WebRequest @p
        $texto = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
        return [pscustomobject]@{ Codigo = [int]$r.StatusCode; Datos = $(if ($texto) { Json $texto } else { $null }) }
    } catch {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { throw }            # no hubo respuesta: el sistema no esta levantado
        $texto = $_.ErrorDetails.Message
        if (-not $texto) {
            $lector = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
            $texto = $lector.ReadToEnd()
        }
        $datos = $null
        try { $datos = Json $texto } catch { $datos = $texto }
        return [pscustomobject]@{ Codigo = [int]$resp.StatusCode; Datos = $datos }
    }
}

function Titulo($n, $texto, $llamada) {
    if ($Pausar -and $n -gt 1) { Read-Host "   (Enter para continuar)" | Out-Null }
    Write-Host ""
    Write-Host "== $n. $texto" -ForegroundColor Cyan
    Write-Host "   $llamada" -ForegroundColor DarkGray
}

function Paso($texto, $obtenido, $esperado, $detalle = "") {
    $ok = $obtenido -eq $esperado
    if ($ok) { Write-Host "   [OK]    $texto -> HTTP $obtenido  $detalle" -ForegroundColor Green }
    else { Write-Host "   [FALLA] $texto -> HTTP $obtenido (esperaba $esperado)  $detalle" -ForegroundColor Red; $script:fallos += $texto }
}

function Mensaje($datos) { if ($datos.detalle) { "`"$($datos.detalle)`"" } else { "" } }

function Token($usuario) {
    $r = Pedir 'POST' '/auth/realms/medicitas/protocol/openid-connect/token' -form @{
        grant_type = 'password'; client_id = 'medicitas-api'; username = $usuario; password = 'medicitas123' }
    if ($r.Codigo -ne 200) { throw "No se pudo pedir el token de $usuario (HTTP $($r.Codigo)). Esta levantado el sistema?" }
    return $r.Datos.access_token
}

# --- 0. Quien hace que
Write-Host "Recorrido de una cita contra $Base" -ForegroundColor Yellow
$recep = Token 'san-rafael-recepcion'
$prof = Token 'san-rafael-laura-mendez'
Write-Host "Tokens de Keycloak: recepcion (san-rafael-recepcion) y profesional (san-rafael-laura-mendez)"

# --- 1. Datos para reservar
Titulo 1 "Catalogo: un servicio, un profesional que lo atiende y un paciente" "GET /api/plataforma/servicios, /profesionales y /pacientes   (recepcion)"
$servicios = (Pedir 'GET' '/api/plataforma/servicios' $recep).Datos
$profesionales = (Pedir 'GET' '/api/plataforma/profesionales' $recep).Datos
$pacientes = (Pedir 'GET' '/api/plataforma/pacientes' $recep).Datos
$activos = @{}; foreach ($s in $servicios) { if ($s.activo) { $activos[$s.id] = $s } }
$pr = $profesionales | Where-Object { $_.activo -and ($_.servicios_ids | Where-Object { $activos.ContainsKey($_) }) } | Select-Object -First 1
$sid = $pr.servicios_ids | Where-Object { $activos.ContainsKey($_) } | Select-Object -First 1
$pac = $pacientes.pacientes[0]
Write-Host "   Profesional: $($pr.nombre)   Servicio: $($activos[$sid].nombre)   Paciente: $($pac.nombre)"

# --- 2. Espacios libres (RF7): el primer dia, desde manana, con al menos 3
Titulo 2 "Espacios libres del profesional (RF7)" "GET /api/agenda/profesionales/{id}/disponibilidad?servicio_id=...&fecha=...   (recepcion)"
$dia = (Get-Date).Date.AddDays(1); $espacios = @()
for ($i = 0; $i -lt 21; $i++) {
    $r = Pedir 'GET' "/api/agenda/profesionales/$($pr.id)/disponibilidad?servicio_id=$sid&fecha=$($dia.ToString('yyyy-MM-dd'))" $recep
    if ($r.Codigo -eq 200 -and @($r.Datos.espacios).Count -ge 3) { $espacios = @($r.Datos.espacios); break }
    $dia = $dia.AddDays(1)
}
Paso "hay espacios libres el $($dia.ToString('yyyy-MM-dd'))" $(if ($espacios.Count) { 200 } else { 404 }) 200 "(primeros: $(($espacios | Select-Object -First 3) -join ', '))"
if (-not $espacios.Count) { Write-Host "Sin espacios libres en 21 dias: no se puede seguir." -ForegroundColor Red; exit 1 }
$ruta = "/api/agenda/profesionales/$($pr.id)/disponibilidad?servicio_id=$sid&fecha=$($dia.ToString('yyyy-MM-dd'))"

# --- 3. Reservar (RF9)
Titulo 3 "Reservar la primera hora (RF9)" "POST /api/agenda/citas   (recepcion)"
$cuerpo = @{ paciente_id = $pac.id; profesional_id = $pr.id; servicio_id = $sid; inicio = $espacios[0] }
$r = Pedir 'POST' '/api/agenda/citas' $recep $cuerpo
Paso "reservar" $r.Codigo 201 "cita $($r.Datos.id)  estado $($r.Datos.estado)  inicio $($r.Datos.inicio)"
$cita = $r.Datos

# --- 4. El mismo espacio otra vez (I1)
Titulo 4 "Pedir ese mismo espacio otra vez: el motor lo impide (I1)" "POST /api/agenda/citas   (el mismo cuerpo)"
$r = Pedir 'POST' '/api/agenda/citas' $recep $cuerpo
Paso "el mismo espacio otra vez" $r.Codigo 409 (Mensaje $r.Datos)

# --- 5. La cache no miente (I8)
Titulo 5 "El espacio reservado ya no se ofrece (I8)" "GET .../disponibilidad   (recepcion)"
$r = Pedir 'GET' $ruta $recep
Paso "el espacio reservado ya no aparece" $(if ($r.Datos.espacios -contains $espacios[0]) { 500 } else { 200 }) 200

# --- 6. Desenlace antes de la hora (RF12)
Titulo 6 "No se puede dar el desenlace de una cita que todavia no empieza (RF12)" "POST /api/agenda/citas/{id}/desenlace   (profesional)"
$r = Pedir 'POST' "/api/agenda/citas/$($cita.id)/desenlace" $prof @{ desenlace = 'ATENDIDA' }
Paso "desenlace antes de la hora" $r.Codigo 422 (Mensaje $r.Datos)

# --- 7. Reprogramar (RF10)
Titulo 7 "Reprogramar a otra hora (RF10): la cita vieja pasa a REPROGRAMADA y nace una nueva" "POST /api/agenda/citas/{id}/reprogramar   (recepcion)"
$libre = $espacios | Where-Object { $_ -ne $espacios[0] } | Select-Object -First 1
$r = Pedir 'POST' "/api/agenda/citas/$($cita.id)/reprogramar" $recep @{ profesional_id = $pr.id; inicio = $libre }
Paso "reprogramar" $r.Codigo 201 "nueva cita $($r.Datos.id)  estado $($r.Datos.estado)  inicio $($r.Datos.inicio)"
$nueva = $r.Datos
$r = Pedir 'GET' $ruta $recep
Paso "el espacio viejo vuelve a ofrecerse (I7)" $(if ($r.Datos.espacios -contains $espacios[0]) { 200 } else { 500 }) 200

# --- 8. Cancelar (RF11) y cancelar otra vez (RF13)
Titulo 8 "Cancelar la cita nueva (RF11): queda el motivo y se libera el espacio" "POST /api/agenda/citas/{id}/cancelar   (recepcion)"
$r = Pedir 'POST' "/api/agenda/citas/$($nueva.id)/cancelar" $recep @{ motivo = 'Demostracion del recorrido' }
Paso "cancelar" $r.Codigo 200 "estado $($r.Datos.estado)"
Titulo 9 "Cancelar otra vez: un estado final no se vuelve a cambiar (RF13)" "POST /api/agenda/citas/{id}/cancelar"
$r = Pedir 'POST' "/api/agenda/citas/$($nueva.id)/cancelar" $recep @{ motivo = 'Otra vez' }
Paso "cancelar una cancelada" $r.Codigo 409 (Mensaje $r.Datos)

# --- 10. Desenlace de una cita ya pasada (RF12): una RESERVADA de la semilla, de la profesional
Titulo 10 "Desenlace ATENDIDA de una cita ya pasada de la semilla (RF12)" "GET /api/agenda/agenda?fecha=...   y   POST /api/agenda/citas/{id}/desenlace   (profesional)"
$pasada = $null
for ($d = 1; $d -le 60 -and -not $pasada; $d++) {
    $r = Pedir 'GET' "/api/agenda/agenda?fecha=$((Get-Date).Date.AddDays(-$d).ToString('yyyy-MM-dd'))" $prof
    if ($r.Codigo -eq 200) { $pasada = @($r.Datos) | Where-Object { $_.estado -eq 'RESERVADA' } | Select-Object -First 1 }
}
if ($pasada) {
    Write-Host "   Cita pasada RESERVADA: $($pasada.id)  inicio $($pasada.inicio)"
    $r = Pedir 'POST' "/api/agenda/citas/$($pasada.id)/desenlace" $prof @{ desenlace = 'ATENDIDA' }
    Paso "desenlace ATENDIDA" $r.Codigo 200 "estado $($r.Datos.estado)"
    $r = Pedir 'POST' "/api/agenda/citas/$($pasada.id)/desenlace" $prof @{ desenlace = 'AUSENTE' }
    Paso "cambiar el desenlace de una cita ya atendida" $r.Codigo 409 (Mensaje $r.Datos)
} else {
    # No es un fallo: la semilla solo deja citas pasadas aun RESERVADAS cuando la base ya tiene unos dias (las citas futuras
    # de la semilla se vuelven pasadas con el tiempo). En una base recien creada no hay ninguna.
    $omitido = $true
    Write-Host "   OMITIDO: no hay citas pasadas todavia RESERVADAS (base recien creada, o ya se usaron todas)." -ForegroundColor Yellow
    Write-Host "   El desenlace sobre una cita pasada tambien lo cubren las pruebas: .\pruebas.ps1" -ForegroundColor Yellow
}

Write-Host ""
if ($fallos.Count -gt 0) { Write-Host "FALLARON: $($fallos -join '; ')" -ForegroundColor Red; exit 1 }
if ($omitido) { Write-Host "BIEN, salvo el desenlace de una cita pasada, que se omitio (ver el paso 10)." -ForegroundColor Yellow; exit 0 }
Write-Host "TODO BIEN: reserva, reprogramacion, cancelacion y desenlace funcionaron." -ForegroundColor Green
