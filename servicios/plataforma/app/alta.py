"""RF1: dar de alta una clínica con su nombre, su identificador y su zona horaria, creando junto con ella su
primer usuario administrador.

QUÉ PARTE DEL ENUNCIADO CUMPLE CADA COSA:
  - «clínica con su nombre, su identificador y su zona horaria» → paso 0 y paso 1 de `crear_clinica`.
  - «creando junto con ella su primer usuario administrador»    → pasos 2 a 4 (`crear_cuenta`, en cuentas.py).
  - «junto con ella» = todo o nada                              → una sola transacción (ver «Orden» abajo).
  - Matriz de permisos: «Alta de clínicas: solo adm. plataforma» → `solo_plataforma` (403 a los demás, RF17).
  - `listar_clinicas` NO lo pide el enunciado: es apoyo para que la pantalla de plataforma muestre lo que creó.
Archivos que intervienen: esquemas.py (NuevaClinica, AltaClinica), cuentas.py y keycloak.py (la cuenta del admin).

Orden de las operaciones (todo dentro de UNA transacción de la base):
  1. INSERT de la clínica. Un identificador repetido falla aquí, antes de tocar a Keycloak (409 por el UNIQUE).
  2. INSERT del usuario administrador con un `keycloak_sub` provisional (un UUID aleatorio).
  3. Se crea la cuenta en Keycloak y se reemplaza el `sub` provisional por el real.
  4. COMMIT. Si 3 falla, el ROLLBACK deshace 1 y 2: o se crean la clínica y su administrador, o ninguno.
Si el COMMIT fallara después de 3, la cuenta de Keycloak queda sin fila en `usuario`: no puede entrar (401, usuario
desconocido) y se retira como compensación.

Por qué el `sub` provisional: la columna `usuario.keycloak_sub` es NOT NULL y UNIQUE, pero el valor real solo existe
después de crear la cuenta en Keycloak. Se inserta primero la fila (para que los errores de la base salgan ANTES de
tocar el proveedor externo, que no se puede deshacer con un ROLLBACK) y luego se corrige el valor.
"""

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_actual

from .cuentas import crear_cuenta
from .esquemas import AltaClinica, ClinicaResumen, NuevaClinica
from .keycloak import KeycloakAdmin, keycloak_admin

# Todas las rutas de este archivo cuelgan de /clinicas. `tags` agrupa las rutas en la documentación (/docs).
router = APIRouter(prefix="/clinicas", tags=["RF1 · Alta de clínicas"])


def solo_plataforma(sesion: Sesion = Depends(sesion_actual)) -> Sesion:
    """Matriz de permisos: el alta de clínicas es solo del administrador de plataforma.

    `Depends(sesion_actual)` hace dos cosas antes de llegar aquí: valida quién llama (sin token válido responde
    401) y busca su rol en la base. Este filtro agrega la segunda mitad de RF17: token válido pero rol
    equivocado responde 403. Las rutas que lo piden con Depends no se ejecutan si este lanza la excepción.
    """
    if sesion.rol != "ADM_PLATAFORMA":
        raise HTTPException(403, "Solo el administrador de plataforma da de alta clínicas")
    return sesion


# `response_model` filtra la respuesta: solo salen los campos de AltaClinica, aunque la fila tenga más.
# `responses` solo alimenta la documentación: declara los códigos de estado posibles (requisito de contrato).
@router.post(
    "",
    response_model=AltaClinica,
    status_code=201,
    responses={
        401: {"description": "Sin token válido"},
        403: {"description": "El rol no es administrador de plataforma"},
        409: {"description": "El identificador de la clínica o el usuario ya existen"},
        422: {"description": "Datos inválidos (identificador, zona horaria desconocida, contraseña corta...)"},
        503: {"description": "El proveedor de identidad no responde"},
    },
)
def crear_clinica(
    nueva: NuevaClinica,  # el cuerpo JSON; FastAPI lo valida con NuevaClinica y responde 422 si no cumple
    sesion: Sesion = Depends(solo_plataforma),  # solo se usa para exigir el rol; el valor en sí no se necesita
    con=CONEXION,  # una conexión con transacción: COMMIT si la ruta termina bien, ROLLBACK si lanza un error
    kc: KeycloakAdmin = Depends(keycloak_admin),  # cliente de Keycloak; las pruebas lo cambian por un doble
):
    """Crea la clínica y su primer administrador (rol ADM_CLINICA) con una contraseña temporal."""

    # --- Paso 0: validar la zona horaria ---------------------------------------------------------------------------
    # El patrón del esquema no puede saber qué zonas existen. Se lo preguntamos al motor, que es quien la usará
    # para interpretar los horarios (ver 002_identidad.sql). `%s` es un parámetro: nunca se concatena texto en el SQL.
    if con.execute("SELECT 1 FROM pg_timezone_names WHERE name = %s", (nueva.zona_horaria,)).fetchone() is None:
        raise HTTPException(422, "La zona horaria no es una zona IANA válida (por ejemplo, America/Costa_Rica)")

    # --- Paso 1: la clínica -----------------------------------------------------------------------------------------
    # Si el identificador ya existe, el UNIQUE de la tabla lanza una excepción y el manejador común
    # (medicitas_comun/app.py) la convierte en 409. No hace falta consultar antes "¿existe?": hacerlo dejaría
    # una ventana donde dos solicitudes simultáneas pasan la consulta y chocan después.
    # RETURNING devuelve la fila insertada, con el id y la fecha que generó la base.
    clinica = con.execute(
        """INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES (%s, %s, %s)
           RETURNING id, nombre, identificador, zona_horaria, creada_en""",
        (nueva.nombre, nueva.identificador, nueva.zona_horaria),
    ).fetchone()

    # --- Pasos 2 a 4: el usuario administrador y su cuenta en Keycloak ---------------------------------------------
    # Se hace en cuentas.crear_cuenta, que también usa RF2: inserta la fila con un sub provisional, crea la cuenta
    # en Keycloak (con la contraseña temporal; `get_secret_value()` es la única forma de leer un SecretStr, así no se
    # imprime por accidente) y reemplaza el sub por el real. La clínica sale del paso 1, nunca de la solicitud (I5).
    # Si Keycloak falla lanza HTTPException (409 o 503) y la transacción completa se deshace: ni clínica ni usuario.
    admin = crear_cuenta(
        con, kc,
        clinica_id=clinica["id"],
        rol="ADM_CLINICA",
        nombre=nueva.admin_nombre,
        usuario=nueva.admin_usuario,
        contrasena=nueva.admin_contrasena.get_secret_value(),
    )

    # El COMMIT lo hace la dependencia CONEXION al terminar esta función, antes de enviar la respuesta.
    # El rol no vino en el RETURNING del paso 2, por eso se agrega a mano.
    return {"clinica": clinica, "admin": {**admin, "rol": "ADM_CLINICA"}}


@router.get("", response_model=list[ClinicaResumen], responses={401: {}, 403: {}})
def listar_clinicas(sesion: Sesion = Depends(solo_plataforma), con=CONEXION):
    """Clínicas con su número de usuarios activos. No expone ningún dato clínico."""
    # LEFT JOIN: una clínica sin usuarios igual aparece (con 0). `count(...) FILTER (WHERE u.activo)` cuenta solo
    # los usuarios activos, para que una baja lógica (RF2) no infle el número.
    return con.execute(
        """SELECT c.id, c.nombre, c.identificador, c.zona_horaria, c.creada_en,
                  count(u.id) FILTER (WHERE u.activo) AS usuarios
           FROM clinica c LEFT JOIN usuario u ON u.clinica_id = c.id
           GROUP BY c.id ORDER BY c.nombre"""
    ).fetchall()
