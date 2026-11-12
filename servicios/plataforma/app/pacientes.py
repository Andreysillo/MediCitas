"""RF14: registrar y actualizar los pacientes de la clínica, con identificación, nombre, fecha de nacimiento y contacto.

QUÉ RUTA CUMPLE CADA PARTE:
  - «registrar» → POST /pacientes (`registrar_paciente`).
  - «actualizar» → PUT /pacientes/{id} (`actualizar_paciente`).
  - (para armar la pantalla) GET /pacientes (buscar) y GET /pacientes/{id} (ficha); no los pide el enunciado, pero
    recepción necesita elegir un paciente y ver sus datos antes de editarlos.
  - Matriz de permisos: «Pacientes: administrador y recepción escriben, profesional solo lectura; administrador de
    plataforma, nada» → `quien_lee` y `quien_escribe`.
Relación con otros requisitos: RF9 (la reserva apunta a un paciente), RF16 (historial), RF18 (bitácora), I2, I5.

La clínica sale SIEMPRE de la sesión (I5). Un paciente de otra clínica responde 404, igual que uno inexistente.

Bitácora (RF18): los datos de contacto son sensibles, así que abrir la ficha (LECTURA) y crear o editar (ESCRITURA)
insertan una fila en `registro_auditoria` DENTRO de la misma transacción de la ruta. Si la inserción falla, todo se
deshace: no puede haber una lectura sin registro. El listado NO trae teléfono ni correo y por eso no se audita; para ver
el contacto hay que abrir la ficha.

Identificación única por clínica: la garantiza el UNIQUE (clinica_id, identificacion) de la tabla. La comprobación previa
solo da un mensaje claro en el caso normal; dos solicitudes simultáneas las resuelve el motor (→ 409).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .esquemas import DatosPaciente, ListaPacientes, Paciente

router = APIRouter(prefix="/pacientes", tags=["RF14 · Pacientes"])

LIMITE_LISTA = 50

_ERRORES = {401: {"description": "Sin token válido"}, 403: {"description": "El rol no tiene acceso a pacientes"}}


def quien_lee(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol not in ("ADM_CLINICA", "RECEPCION", "PROFESIONAL"):
        raise HTTPException(403, "Tu rol no tiene acceso a los pacientes")
    return sesion


def quien_escribe(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol not in ("ADM_CLINICA", "RECEPCION"):
        raise HTTPException(403, "Tu rol no puede registrar ni modificar pacientes")
    return sesion


def _auditar(con, sesion: Sesion, paciente_id: UUID, accion: str) -> None:
    """RF18: quién, qué, sobre cuál paciente y cuándo (`ocurrido_en` lo pone el motor)."""
    con.execute(
        """INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso)
           VALUES (%s, %s, %s, %s, 'CONTACTO_PACIENTE')""",
        (sesion.clinica_id, sesion.usuario_id, paciente_id, accion),
    )


def _ya_existe(con, sesion: Sesion, identificacion: str, propio: UUID | None = None) -> None:
    fila = con.execute(
        "SELECT 1 FROM paciente WHERE clinica_id = %s AND identificacion = %s AND id IS DISTINCT FROM %s",
        (sesion.clinica_id, identificacion, propio),
    ).fetchone()
    if fila:
        raise HTTPException(409, "Ya existe un paciente con esa identificación en la clínica")


_COLUMNAS = "id, identificacion, nombre, fecha_nacimiento, telefono, correo"


@router.get("", response_model=ListaPacientes, responses=_ERRORES)
def listar_pacientes(
    q: str = Query("", max_length=80, description="Texto que se busca en el nombre o la identificación"),
    sesion: Sesion = Depends(quien_lee),
    con=CONEXION,
):
    """Pacientes de la clínica por orden alfabético, sin datos de contacto. Trae los primeros 50 y el total."""
    # Los comodines del texto buscado se escapan: «%» o «_» se buscan literalmente. La consulta va parametrizada.
    patron = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    donde = "clinica_id = %s AND (nombre ILIKE %s OR identificacion ILIKE %s)"
    params = (sesion.clinica_id, patron, patron)
    total = con.execute(f"SELECT count(*) AS n FROM paciente WHERE {donde}", params).fetchone()["n"]
    filas = con.execute(
        f"SELECT id, nombre, identificacion, fecha_nacimiento FROM paciente WHERE {donde} ORDER BY nombre, id LIMIT {LIMITE_LISTA}",
        params,
    ).fetchall()
    return {"total": total, "pacientes": filas}


@router.get("/{paciente_id}", response_model=Paciente, responses={**_ERRORES, 404: {"description": "No existe en esta clínica"}})
def ver_paciente(paciente_id: UUID, sesion: Sesion = Depends(quien_lee), con=CONEXION):
    """Ficha completa, con teléfono y correo. Cada lectura queda en la bitácora (RF18)."""
    fila = con.execute(
        f"SELECT {_COLUMNAS} FROM paciente WHERE id = %s AND clinica_id = %s", (paciente_id, sesion.clinica_id)
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Paciente no encontrado")
    _auditar(con, sesion, paciente_id, "LECTURA")
    return fila


@router.post(
    "", response_model=Paciente, status_code=201,
    responses={**_ERRORES, 409: {"description": "Ya existe un paciente con esa identificación en la clínica"},
               422: {"description": "Datos inválidos"}},
)
def registrar_paciente(datos: DatosPaciente, sesion: Sesion = Depends(quien_escribe), con=CONEXION):
    """Registra un paciente en la clínica de la sesión. La escritura queda en la bitácora (RF18)."""
    _ya_existe(con, sesion, datos.identificacion)
    fila = con.execute(
        f"""INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento, telefono, correo)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_COLUMNAS}""",
        (sesion.clinica_id, datos.identificacion, datos.nombre, datos.fecha_nacimiento, datos.telefono, datos.correo),
    ).fetchone()
    _auditar(con, sesion, fila["id"], "ESCRITURA")
    return fila


@router.put(
    "/{paciente_id}", response_model=Paciente,
    responses={**_ERRORES, 404: {"description": "No existe en esta clínica"},
               409: {"description": "Esa identificación ya la tiene otro paciente"}, 422: {"description": "Datos inválidos"}},
)
def actualizar_paciente(paciente_id: UUID, datos: DatosPaciente, sesion: Sesion = Depends(quien_escribe), con=CONEXION):
    """Reemplaza los datos del paciente (todos los campos). La escritura queda en la bitácora (RF18)."""
    _ya_existe(con, sesion, datos.identificacion, paciente_id)
    fila = con.execute(
        f"""UPDATE paciente SET identificacion = %s, nombre = %s, fecha_nacimiento = %s, telefono = %s, correo = %s
            WHERE id = %s AND clinica_id = %s RETURNING {_COLUMNAS}""",
        (datos.identificacion, datos.nombre, datos.fecha_nacimiento, datos.telefono, datos.correo, paciente_id, sesion.clinica_id),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Paciente no encontrado")
    _auditar(con, sesion, paciente_id, "ESCRITURA")
    return fila
