"""RF2: gestionar los usuarios de una clínica, con alta, baja lógica y asignación de rol.

QUÉ RUTA CUMPLE CADA PALABRA DEL ENUNCIADO:
  - «alta»                  → POST  /usuarios                 (`crear_usuario`, apoyada en cuentas.py y keycloak.py)
  - «baja lógica»           → PATCH /usuarios/{id}/activo     (`cambiar_activo`; `activo: true` reactiva)
  - «asignación de rol»     → PATCH /usuarios/{id}/rol        (`cambiar_rol`)
  - (para ver el resultado) → GET   /usuarios                 (`listar_usuarios`; no lo pide el enunciado)
  - «pertenece a exactamente una clínica, salvo el adm. de plataforma» → la clínica sale de la sesión y el rol
    ADM_PLATAFORMA no es asignable (RolDeClinica en esquemas.py); el CHECK de la tabla `usuario` lo refuerza.
  - Matriz de permisos: «Usuarios, servicios y profesionales: solo adm. de clínica» → `admin_de_clinica`.
Reglas propias que el enunciado no dicta pero el diseño necesita: nadie cambia su propio rol ni se da de baja; la clínica
conserva siempre un administrador activo; un profesional registrado (RF4) no cambia de rol; la baja de un profesional lo
saca de la disponibilidad (RF7) sin cancelar sus citas.
Relación con otros requisitos: RF17 (la baja corta el acceso porque sesion.py revisa `activo`), RF4 (profesionales.py
bloquea la misma fila de usuario para no registrar a alguien cuyo rol está cambiando).

Solo el administrador de la clínica (matriz de permisos). La clínica sale SIEMPRE de la sesión: un usuario de otra
clínica responde 404 igual que uno inexistente (I5). Las credenciales viven en Keycloak; aquí solo se guarda quién
pertenece a la clínica y con qué rol. La fuente de verdad del rol es la tabla `usuario` (ver comun/sesion.py).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .cuentas import crear_cuenta
from .esquemas import CambioActivo, CambioDeActivo, CambioRol, NuevoUsuario, UsuarioVista
from .keycloak import KeycloakAdmin, keycloak_admin

router = APIRouter(prefix="/usuarios", tags=["RF2 · Usuarios de la clínica"])

_ERRORES = {
    401: {"description": "Sin token válido"},
    403: {"description": "El rol no es administrador de clínica"},
    404: {"description": "El usuario no existe en esta clínica"},
}


def admin_de_clinica(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    """`sesion_de_clinica` ya rechaza al administrador de plataforma (no tiene clínica); aquí se exige el rol."""
    if sesion.rol != "ADM_CLINICA":
        raise HTTPException(403, "Solo el administrador de clínica gestiona los usuarios")
    return sesion


_VISTA = """SELECT u.id, u.nombre, r.codigo AS rol, u.activo,
                   EXISTS (SELECT 1 FROM profesional p WHERE p.usuario_id = u.id) AS es_profesional,
                   (u.id = %s) AS yo
            FROM usuario u JOIN rol r ON r.id = u.rol_id
            WHERE u.clinica_id = %s"""


def _vista(con, sesion: Sesion, usuario_id: UUID) -> dict:
    return con.execute(_VISTA + " AND u.id = %s", (sesion.usuario_id, sesion.clinica_id, usuario_id)).fetchone()


def _bloquear_clinica(con, sesion: Sesion) -> None:
    """Serializa los cambios de usuarios de una misma clínica. Sin esto, dos administradores que se dan de baja
    mutuamente a la vez pasarían ambos la revisión «queda otro administrador» y la clínica quedaría sin ninguno."""
    con.execute("SELECT 1 FROM clinica WHERE id = %s FOR NO KEY UPDATE", (sesion.clinica_id,))


def _buscar(con, sesion: Sesion, usuario_id: UUID) -> dict:
    fila = con.execute(
        """SELECT u.id, u.activo, r.codigo AS rol FROM usuario u JOIN rol r ON r.id = u.rol_id
           WHERE u.id = %s AND u.clinica_id = %s FOR UPDATE OF u""",
        (usuario_id, sesion.clinica_id),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Usuario no encontrado")
    return fila


def _debe_quedar_otro_admin(con, sesion: Sesion, usuario_id: UUID) -> None:
    """La clínica nunca se queda sin administrador activo: quien lo gestiona es solo el administrador de la clínica."""
    otro = con.execute(
        """SELECT 1 FROM usuario u JOIN rol r ON r.id = u.rol_id
           WHERE u.clinica_id = %s AND r.codigo = 'ADM_CLINICA' AND u.activo AND u.id <> %s LIMIT 1""",
        (sesion.clinica_id, usuario_id),
    ).fetchone()
    if otro is None:
        raise HTTPException(409, "La clínica debe conservar al menos un administrador activo")


@router.get("", response_model=list[UsuarioVista], responses=_ERRORES)
def listar_usuarios(sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Usuarios de la clínica de quien consulta: primero los activos, luego por nombre."""
    return con.execute(_VISTA + " ORDER BY u.activo DESC, u.nombre", (sesion.usuario_id, sesion.clinica_id)).fetchall()


@router.post(
    "", response_model=UsuarioVista, status_code=201,
    responses={**_ERRORES, 409: {"description": "El nombre de usuario ya existe"}, 422: {"description": "Datos inválidos"},
               503: {"description": "El proveedor de identidad no responde"}},
)
def crear_usuario(
    nuevo: NuevoUsuario,
    sesion: Sesion = Depends(admin_de_clinica),
    con=CONEXION,
    kc: KeycloakAdmin = Depends(keycloak_admin),
):
    """Da de alta un usuario en la clínica de quien llama, con su cuenta en Keycloak y una contraseña temporal."""
    creado = crear_cuenta(
        con, kc, clinica_id=sesion.clinica_id, rol=nuevo.rol, nombre=nuevo.nombre,
        usuario=nuevo.usuario, contrasena=nuevo.contrasena.get_secret_value(),
    )
    return _vista(con, sesion, creado["id"])


@router.patch(
    "/{usuario_id}/rol", response_model=UsuarioVista,
    responses={**_ERRORES, 409: {"description": "Cambiaría tu propio rol, dejaría la clínica sin administrador o es un profesional registrado"}},
)
def cambiar_rol(usuario_id: UUID, cambio: CambioRol, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Asigna otro rol al usuario."""
    _bloquear_clinica(con, sesion)
    destino = _buscar(con, sesion, usuario_id)
    if destino["id"] == sesion.usuario_id:
        raise HTTPException(409, "No puedes cambiar tu propio rol")
    if destino["rol"] == "ADM_CLINICA" and cambio.rol != "ADM_CLINICA":
        _debe_quedar_otro_admin(con, sesion, usuario_id)
    # Su registro de profesional (agenda, servicios, citas) depende de que siga siendo PROFESIONAL.
    if cambio.rol != "PROFESIONAL" and con.execute(
        "SELECT 1 FROM profesional WHERE usuario_id = %s AND clinica_id = %s", (usuario_id, sesion.clinica_id)
    ).fetchone():
        raise HTTPException(409, "Es un profesional registrado: no puede cambiar de rol")
    con.execute(
        "UPDATE usuario SET rol_id = (SELECT id FROM rol WHERE codigo = %s) WHERE id = %s AND clinica_id = %s",
        (cambio.rol, usuario_id, sesion.clinica_id),
    )
    return _vista(con, sesion, usuario_id)


@router.patch(
    "/{usuario_id}/activo", response_model=CambioDeActivo,
    responses={**_ERRORES, 409: {"description": "Te darías de baja o dejaría la clínica sin administrador"}},
)
def cambiar_activo(usuario_id: UUID, cambio: CambioActivo, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Baja lógica (`activo: false`) o reactivación. Nada se borra: las citas y la bitácora siguen apuntando al usuario.
    Si es profesional, también sale (o vuelve) de la disponibilidad; sus citas reservadas NO se cancelan, se informa
    cuántas quedan para que recepción las reprograme. Un usuario dado de baja recibe 403 en su siguiente solicitud."""
    _bloquear_clinica(con, sesion)
    destino = _buscar(con, sesion, usuario_id)
    if not cambio.activo:
        if destino["id"] == sesion.usuario_id:
            raise HTTPException(409, "No puedes darte de baja a ti mismo")
        if destino["rol"] == "ADM_CLINICA" and destino["activo"]:
            _debe_quedar_otro_admin(con, sesion, usuario_id)
    con.execute("UPDATE usuario SET activo = %s WHERE id = %s AND clinica_id = %s", (cambio.activo, usuario_id, sesion.clinica_id))
    con.execute("UPDATE profesional SET activo = %s WHERE usuario_id = %s AND clinica_id = %s", (cambio.activo, usuario_id, sesion.clinica_id))

    pendientes = 0
    if not cambio.activo:
        pendientes = con.execute(
            """SELECT count(*) AS n FROM cita c JOIN profesional p ON p.id = c.profesional_id AND p.clinica_id = c.clinica_id
               WHERE p.usuario_id = %s AND c.clinica_id = %s AND c.estado = 'RESERVADA' AND c.fin > now()""",
            (usuario_id, sesion.clinica_id),
        ).fetchone()["n"]
    return {"usuario": _vista(con, sesion, usuario_id), "citas_pendientes": pendientes}
