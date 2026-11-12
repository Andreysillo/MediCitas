"""RF4: registrar profesionales con su especialidad y asociarles los servicios que están habilitados para atender.

QUÉ RUTA CUMPLE CADA PARTE:
  - «registrar profesionales con su especialidad» → POST /profesionales (`registrar_profesional`) y PUT
    /profesionales/{id} (`actualizar_profesional`, que también permite cambiarla).
  - «asociarles los servicios que están habilitados» → el campo `servicios_ids` de ambas rutas, que `_aplicar_servicios`
    traduce a filas de `profesional_servicio`.
  - «Un profesional atiende solo los servicios que tiene asociados» (sección de entidades del enunciado) → esa tabla,
    y la clave foránea de `cita` hacia ella lo hace cumplir en el motor.
  - (para armar la pantalla) GET /profesionales y GET /profesionales/usuarios-libres; no los pide el enunciado.
  - Matriz de permisos: «Usuarios, servicios y profesionales: solo adm. de clínica» → `admin_de_clinica`.
Relación con otros requisitos: RF2 (el profesional ES un usuario con rol PROFESIONAL), RF3 (sus servicios son del
catálogo y de su especialidad), RF5/RF6 (el horario y los bloqueos cuelgan de la fila `profesional`), RF7/RF9.

Solo el administrador de la clínica (matriz de permisos). La clínica sale SIEMPRE de la sesión (I5).

Un profesional es un USUARIO de la clínica con rol PROFESIONAL al que se le agrega su especialidad, su número de
colegiado y los servicios que atiende. Alta y baja del usuario son de RF2 (la baja del usuario también da de baja al
profesional); aquí no se duplican.

Reglas:
  - Un profesional solo atiende servicios de SU especialidad (RF3, RF4).
  - Los servicios se declaran completos (`servicios_ids`): lo que se quita se DESHABILITA, no se borra, porque las
    citas ya hechas apuntan a la pareja (profesional, servicio) y la clave foránea de `cita` lo impediría.
  - La agenda comprueba `profesional_servicio.activo` ANTES de consultar la caché (agenda/app/disponibilidad.py), así
    que quitar un servicio aquí no deja disponibilidad falsa (I8), aunque este servicio no hable con Redis.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .esquemas import DatosProfesional, NuevoProfesional, Profesional, UsuarioLibre

router = APIRouter(prefix="/profesionales", tags=["RF4 · Profesionales"])

_ERRORES = {
    401: {"description": "Sin token válido"},
    403: {"description": "El rol no es administrador de clínica"},
}


def admin_de_clinica(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol != "ADM_CLINICA":
        raise HTTPException(403, "Solo el administrador de clínica gestiona los profesionales")
    return sesion


# Los JOIN usan la clave compuesta (clinica_id, id), igual que las claves foráneas: nunca cruzan de clínica.
_PROFESIONAL = """SELECT p.id, u.nombre, p.especialidad_id, e.nombre AS especialidad, p.numero_colegiado, p.activo,
                          COALESCE(array_agg(ps.servicio_id) FILTER (WHERE ps.activo), '{}'::uuid[]) AS servicios_ids
                   FROM profesional p
                   JOIN usuario u      ON u.clinica_id = p.clinica_id AND u.id = p.usuario_id
                   JOIN especialidad e ON e.clinica_id = p.clinica_id AND e.id = p.especialidad_id
                   LEFT JOIN profesional_servicio ps ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.id
                   WHERE p.clinica_id = %s"""
_AGRUPAR = " GROUP BY p.id, u.nombre, e.nombre"


def _uno(con, sesion: Sesion, profesional_id: UUID) -> dict:
    return con.execute(_PROFESIONAL + " AND p.id = %s" + _AGRUPAR, (sesion.clinica_id, profesional_id)).fetchone()


def _validar(con, sesion: Sesion, datos: DatosProfesional) -> list[UUID]:
    """Comprueba la especialidad y los servicios; devuelve los ids sin repetir."""
    if con.execute(
        "SELECT 1 FROM especialidad WHERE id = %s AND clinica_id = %s", (datos.especialidad_id, sesion.clinica_id)
    ).fetchone() is None:
        raise HTTPException(422, "La especialidad no existe en esta clínica")
    ids = list(set(datos.servicios_ids))
    validos = con.execute(
        "SELECT count(*) AS n FROM servicio WHERE clinica_id = %s AND especialidad_id = %s AND id = ANY(%s::uuid[])",
        (sesion.clinica_id, datos.especialidad_id, ids),
    ).fetchone()["n"]
    if validos != len(ids):
        raise HTTPException(422, "Un servicio no existe o no corresponde a la especialidad del profesional")
    return ids


def _aplicar_servicios(con, sesion: Sesion, profesional_id: UUID, ids: list[UUID]) -> None:
    """Deja habilitados exactamente `ids`: habilita los de la lista, deshabilita los demás y agrega los nuevos."""
    con.execute(
        "UPDATE profesional_servicio SET activo = (servicio_id = ANY(%s::uuid[])) WHERE clinica_id = %s AND profesional_id = %s",
        (ids, sesion.clinica_id, profesional_id),
    )
    con.execute(
        """INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id)
           SELECT %s, %s, s FROM unnest(%s::uuid[]) AS s ON CONFLICT DO NOTHING""",
        (sesion.clinica_id, profesional_id, ids),
    )


@router.get("", response_model=list[Profesional], responses=_ERRORES)
def listar_profesionales(sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Profesionales de la clínica, con los ids de los servicios que tienen habilitados."""
    return con.execute(_PROFESIONAL + _AGRUPAR + " ORDER BY u.nombre", (sesion.clinica_id,)).fetchall()


@router.get("/usuarios-libres", response_model=list[UsuarioLibre], responses=_ERRORES)
def usuarios_libres(sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Usuarios activos con rol PROFESIONAL que todavía no tienen su registro de profesional."""
    return con.execute(
        """SELECT u.id, u.nombre FROM usuario u JOIN rol r ON r.id = u.rol_id
           WHERE u.clinica_id = %s AND r.codigo = 'PROFESIONAL' AND u.activo
             AND NOT EXISTS (SELECT 1 FROM profesional p WHERE p.usuario_id = u.id)
           ORDER BY u.nombre""",
        (sesion.clinica_id,),
    ).fetchall()


@router.post(
    "", response_model=Profesional, status_code=201,
    responses={**_ERRORES, 409: {"description": "Ese usuario ya está registrado como profesional"},
               422: {"description": "Datos inválidos, usuario sin rol de profesional o servicio de otra especialidad"}},
)
def registrar_profesional(nuevo: NuevoProfesional, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Registra a un usuario con rol PROFESIONAL como profesional, con su especialidad y servicios."""
    # FOR SHARE sobre el usuario: RF2 toma FOR UPDATE de esa fila para cambiar su rol o darlo de baja. Así, o el cambio
    # entra antes y aquí se ve el rol nuevo, o entra después y ve que ya es profesional. Sin esto, un usuario podría
    # quedar registrado como profesional con otro rol.
    usuario = con.execute(
        """SELECT u.id FROM usuario u JOIN rol r ON r.id = u.rol_id
           WHERE u.id = %s AND u.clinica_id = %s AND r.codigo = 'PROFESIONAL' AND u.activo FOR SHARE OF u""",
        (nuevo.usuario_id, sesion.clinica_id),
    ).fetchone()
    if usuario is None:
        raise HTTPException(422, "El usuario no existe en esta clínica, está dado de baja o no tiene rol de profesional")
    ids = _validar(con, sesion, nuevo)
    # Mensaje claro en el caso normal; el UNIQUE de profesional.usuario_id cubre dos solicitudes simultáneas (→ 409).
    if con.execute("SELECT 1 FROM profesional WHERE usuario_id = %s", (nuevo.usuario_id,)).fetchone():
        raise HTTPException(409, "Ese usuario ya está registrado como profesional")

    profesional = con.execute(
        """INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (sesion.clinica_id, nuevo.usuario_id, nuevo.especialidad_id, nuevo.numero_colegiado.strip()),
    ).fetchone()
    _aplicar_servicios(con, sesion, profesional["id"], ids)
    return _uno(con, sesion, profesional["id"])


@router.put(
    "/{profesional_id}", response_model=Profesional,
    responses={**_ERRORES, 404: {"description": "El profesional no existe en esta clínica"},
               422: {"description": "Datos inválidos o servicio de otra especialidad"}},
)
def actualizar_profesional(profesional_id: UUID, datos: DatosProfesional, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Cambia especialidad, número de colegiado y servicios. Reemplaza la lista de servicios completa."""
    # Mismo bloqueo de fila que usan la reserva y los bloqueos de agenda (README de servicios): los cambios que
    # afectan lo que el profesional puede atender se serializan con las reservas.
    fila = con.execute(
        "SELECT id FROM profesional WHERE id = %s AND clinica_id = %s FOR NO KEY UPDATE", (profesional_id, sesion.clinica_id)
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Profesional no encontrado")
    ids = _validar(con, sesion, datos)
    con.execute(
        "UPDATE profesional SET especialidad_id = %s, numero_colegiado = %s WHERE id = %s AND clinica_id = %s",
        (datos.especialidad_id, datos.numero_colegiado.strip(), profesional_id, sesion.clinica_id),
    )
    _aplicar_servicios(con, sesion, profesional_id, ids)
    return _uno(con, sesion, profesional_id)
