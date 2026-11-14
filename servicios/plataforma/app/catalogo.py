"""RF3: mantener el catálogo de servicios de la clínica. Cada servicio lleva nombre, duración en minutos y la
especialidad que requiere.

QUÉ RUTA CUMPLE CADA PARTE:
  - «mantener el catálogo» (alta, edición, baja) → POST /servicios, PATCH /servicios/{id} (activo=false es la baja),
                                                   GET /servicios para listar.
  - «nombre, duración en minutos» → NuevoServicio / CambioServicio en esquemas.py (duración de 5 a 480).
  - «la especialidad que requiere» → `especialidad_id` en NuevoServicio. Las especialidades son un catálogo propio de
    cada clínica, por eso este archivo también trae GET/POST /especialidades (apoyo de RF3: sin ellas no hay a qué apuntar).
  - Matriz de permisos: «Usuarios, servicios y profesionales: solo adm. de clínica» → `admin_de_clinica` para escribir.
    LEER servicios y profesionales (GET /servicios, GET /profesionales) lo pueden todos los roles de la clínica
    (`lee_catalogo`): amplía la matriz, que permite ampliarla si se justifica. Sin esa lectura, recepción (que reserva,
    RF9) y el profesional (que consulta disponibilidad, RF7) no tendrían de dónde sacar el `servicio_id` que esas
    rutas piden. Lo que no se amplía: crear, editar, GET /especialidades y GET /profesionales/usuarios-libres.
Relación con otros requisitos: I4 (la duración del servicio fija el tamaño de la cita), RF4 (un profesional solo atiende
servicios de su especialidad), RF7/RF9 (agenda lee `duracion_minutos` y `activo`).

Solo el administrador de la clínica (matriz de permisos). La clínica sale SIEMPRE de la sesión (I5).

La especialidad es un catálogo propio de cada clínica (ver 002_identidad.sql), así que para poder crear un servicio
hay que poder crear especialidades: por eso este archivo también tiene /especialidades.

Decisiones:
  - Dos garantías las da el motor, no el código: el nombre del servicio es único dentro de la clínica (UNIQUE →
    409) y la clave foránea COMPUESTA (clinica_id, especialidad_id) impide usar la especialidad de otra clínica
    (→ 422). No se consulta «¿existe?» antes de insertar: esa consulta tendría una ventana de carrera.
  - Un servicio no se borra: se desactiva (`activo`). Las citas ya hechas apuntan a él. agenda no ofrece ni reserva
    un servicio inactivo (reserva.py, disponibilidad.py).
  - Cambiar la duración solo afecta a las citas NUEVAS: cada cita guarda su propio `fin` (I4). La caché de
    disponibilidad lleva la duración en la clave (agenda/app/cache.py), así que editar un servicio desde aquí no
    deja copias falsas (I8) aunque este servicio no hable con Redis.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .esquemas import CambioServicio, Especialidad, NuevaEspecialidad, NuevoServicio, Servicio

router = APIRouter(tags=["RF3 · Catálogo de servicios"])

_ERRORES = {
    401: {"description": "Sin token válido"},
    403: {"description": "El rol no es administrador de clínica"},
}


def admin_de_clinica(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol != "ADM_CLINICA":
        raise HTTPException(403, "Solo el administrador de clínica mantiene el catálogo")
    return sesion


def lee_catalogo(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    """Leer el catálogo (servicios y profesionales): cualquier rol con clínica. `sesion_de_clinica` ya deja fuera al
    administrador de plataforma (403: no ve datos de clínicas) y a quien no tiene sesión (401)."""
    return sesion


# ---------- Especialidades ----------


@router.get("/especialidades", response_model=list[Especialidad], responses=_ERRORES)
def listar_especialidades(sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    return con.execute("SELECT id, nombre FROM especialidad WHERE clinica_id = %s ORDER BY nombre", (sesion.clinica_id,)).fetchall()


@router.post(
    "/especialidades", response_model=Especialidad, status_code=201,
    responses={**_ERRORES, 409: {"description": "Ya existe una especialidad con ese nombre"}, 422: {"description": "Datos inválidos"}},
)
def crear_especialidad(nueva: NuevaEspecialidad, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    return con.execute(
        "INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, %s) RETURNING id, nombre", (sesion.clinica_id, nueva.nombre)
    ).fetchone()


# ---------- Servicios ----------

# El JOIN a especialidad usa la clave compuesta, igual que la clave foránea: nunca cruza de clínica.
_SERVICIO = """SELECT s.id, s.nombre, s.duracion_minutos, s.especialidad_id, e.nombre AS especialidad, s.activo
               FROM servicio s JOIN especialidad e ON e.clinica_id = s.clinica_id AND e.id = s.especialidad_id
               WHERE s.clinica_id = %s"""


@router.get("/servicios", response_model=list[Servicio], responses={401: _ERRORES[401], 403: {"description": "No eres de una clínica"}})
def listar_servicios(sesion: Sesion = Depends(lee_catalogo), con=CONEXION):
    """Todos los servicios de la clínica, también los desactivados."""
    return con.execute(_SERVICIO + " ORDER BY e.nombre, s.nombre", (sesion.clinica_id,)).fetchall()


@router.post(
    "/servicios", response_model=Servicio, status_code=201,
    responses={**_ERRORES, 409: {"description": "Ya existe un servicio con ese nombre"},
               422: {"description": "Datos inválidos o la especialidad no existe en esta clínica"}},
)
def crear_servicio(nuevo: NuevoServicio, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    servicio = con.execute(
        "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, %s, %s, %s) RETURNING id",
        (sesion.clinica_id, nuevo.nombre, nuevo.duracion_minutos, nuevo.especialidad_id),
    ).fetchone()
    return con.execute(_SERVICIO + " AND s.id = %s", (sesion.clinica_id, servicio["id"])).fetchone()


@router.patch(
    "/servicios/{servicio_id}", response_model=Servicio,
    responses={**_ERRORES, 404: {"description": "El servicio no existe en esta clínica"},
               409: {"description": "Ya existe un servicio con ese nombre"}, 422: {"description": "Datos inválidos"}},
)
def actualizar_servicio(servicio_id: UUID, cambio: CambioServicio, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Edita nombre, duración y estado. La especialidad no cambia."""
    # El filtro por clínica va en el propio UPDATE: un servicio de otra clínica no se toca y responde 404 (I5).
    fila = con.execute(
        """UPDATE servicio SET nombre = %s, duracion_minutos = %s, activo = %s
           WHERE id = %s AND clinica_id = %s RETURNING id""",
        (cambio.nombre, cambio.duracion_minutos, cambio.activo, servicio_id, sesion.clinica_id),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Servicio no encontrado")
    return con.execute(_SERVICIO + " AND s.id = %s", (sesion.clinica_id, servicio_id)).fetchone()
