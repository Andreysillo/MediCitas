"""Crear un usuario de una clínica: su fila en la base y su cuenta en Keycloak, como una sola operación.

Lo comparten RF1 (el primer administrador de una clínica nueva) y RF2 (los usuarios que el administrador agrega después).

Orden: primero la fila en la base con un `keycloak_sub` provisional, después la cuenta en Keycloak, y al final se
reemplaza el sub provisional por el real. Así los errores de la base (que se pueden deshacer con ROLLBACK) salen
ANTES de tocar el proveedor externo (que no se puede deshacer). Si Keycloak falla lanza HTTPException y la
transacción de la ruta se deshace completa.
"""

from uuid import UUID

from .keycloak import KeycloakAdmin


def crear_cuenta(con, kc: KeycloakAdmin, *, clinica_id: UUID, rol: str, nombre: str, usuario: str, contrasena: str) -> dict:
    """Devuelve {id, nombre, activo} del usuario creado. `clinica_id` sale de la sesión o de la clínica recién creada,
    nunca del cuerpo de la solicitud (I5)."""
    fila = con.execute(
        """INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
           SELECT %s, r.id, gen_random_uuid()::text, %s FROM rol r WHERE r.codigo = %s
           RETURNING id, nombre, activo""",
        (clinica_id, nombre, rol),
    ).fetchone()

    sub = kc.crear_usuario(usuario=usuario, nombre=nombre, contrasena=contrasena, rol=rol)

    # Si este UPDATE fallara, la cuenta recién creada no tiene dónde apuntar: se retira antes de propagar el error.
    try:
        con.execute("UPDATE usuario SET keycloak_sub = %s WHERE id = %s", (sub, fila["id"]))
    except Exception:
        kc.eliminar_usuario(sub)
        raise
    return fila
