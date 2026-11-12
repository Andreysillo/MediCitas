"""Cliente mínimo de la API de administración de Keycloak: solo lo que RF1 necesita (crear un usuario del realm).

MediCitas no implementa el inicio de sesión ni guarda contraseñas: aquí solo se le pide a Keycloak que cree la
cuenta del primer administrador. La contraseña viaja a Keycloak y no se guarda ni se registra.

A QUÉ REQUISITOS SIRVE:
  - RF1: crea la cuenta del primer administrador de una clínica nueva.
  - RF2: crea la cuenta de cada usuario que el administrador agrega después (mismo código, vía cuentas.py).
  - RF17 (identidad delegada): es la razón de que MediCitas no guarde contraseñas ni escriba su propio login.
  - RF3 y RF4 NO usan este archivo (no tocan identidades).

Cómo encaja con el resto:
  - alta.py (RF1) recibe este cliente como dependencia (`Depends(keycloak_admin)`) y llama a `crear_usuario`.
  - Es OTRA cosa distinta de comun/sesion.py. Aquel archivo VALIDA tokens de quien ya inició sesión (lee las llaves
    públicas, no necesita contraseña). Este archivo ADMINISTRA Keycloak (crea cuentas), así que necesita
    credenciales de administrador del proveedor.
  - Habla con Keycloak por la red interna del compose (http://keycloak:8080), nunca por la dirección pública.
"""

import os

import httpx
from fastapi import HTTPException

# Nombre del realm de MediCitas (ver keycloak/realm-export.json). Todas las cuentas de la aplicación viven ahí.
REALM = "medicitas"


class KeycloakAdmin:
    def __init__(self, base: str, usuario: str, contrasena: str):
        # `base` es la dirección INTERNA del compose (http://keycloak:8080), no la pública.
        # `usuario` y `contrasena` son los de la consola de administración de Keycloak (KEYCLOAK_ADMIN*),
        # NO los de las personas que usan MediCitas.
        self.base, self.usuario, self.contrasena = base.rstrip("/"), usuario, contrasena

    @classmethod
    def desde_entorno(cls) -> "KeycloakAdmin":
        """Arma el cliente con las variables que el compose le pasa al servicio plataforma."""
        return cls(
            os.getenv("KEYCLOAK_URL", "http://keycloak:8080"),
            os.environ.get("KEYCLOAK_ADMIN", "admin"),
            os.environ.get("KEYCLOAK_ADMIN_PASSWORD", ""),
        )

    def _cabecera_admin(self, http: httpx.Client) -> dict:
        """Pide un token de administrador. Se hace en cada operación: son pocas y así no hay token vencido que cuidar."""
        # El token se pide al realm "master" (donde vive el administrador de Keycloak) con el client "admin-cli",
        # que Keycloak trae de fábrica. Este token NO sirve para MediCitas: solo abre la API de administración.
        token = http.post(
            f"{self.base}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": self.usuario, "password": self.contrasena},
        )
        token.raise_for_status()  # contraseña de administrador mala o Keycloak con error: lanza httpx.HTTPError
        return {"Authorization": f"Bearer {token.json()['access_token']}"}

    def crear_usuario(self, *, usuario: str, nombre: str, contrasena: str, rol: str) -> str:
        """Crea el usuario con contraseña temporal y le asigna el rol del realm. Devuelve su `sub` (id en Keycloak).
        409 si el nombre de usuario ya existe; 503 si Keycloak no responde."""
        try:
            # Un solo cliente HTTP para los tres pasos. timeout=5: esto corre con una conexión de la base tomada
            # (la transacción de alta.py sigue abierta), así que un Keycloak lento no debe retenerla mucho.
            with httpx.Client(timeout=5) as http:
                cab = self._cabecera_admin(http)
                admin = f"{self.base}/admin/realms/{REALM}"

                # --- Paso 1: crear la cuenta -----------------------------------------------------------------
                # Keycloak guarda nombre y apellido por separado: se parte el nombre completo en la primera palabra
                # y el resto. Si solo hay una palabra, el apellido es "-" porque el campo no puede ir vacío.
                partes = nombre.split(maxsplit=1)
                r = http.post(f"{admin}/users", headers=cab, json={
                    "username": usuario,
                    "firstName": partes[0],
                    "lastName": partes[1] if len(partes) > 1 else "-",
                    "enabled": True,
                    "emailVerified": True,
                    # temporary=True: Keycloak obliga a cambiar la contraseña en el primer inicio de sesión.
                    "credentials": [{"type": "password", "value": contrasena, "temporary": True}],
                })
                if r.status_code == 409:
                    raise HTTPException(409, "Ya existe un usuario con ese nombre de usuario en el proveedor de identidad")
                r.raise_for_status()
                # Keycloak no devuelve el usuario creado: manda su dirección en la cabecera Location
                # (.../users/<id>). El último tramo es el id, y ese id es el `sub` que irá en sus tokens.
                sub = r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

                # --- Paso 2: asignarle el rol -----------------------------------------------------------------
                # El rol (ADM_CLINICA) ya existe en el realm. Se busca su definición y se asigna al usuario.
                # La fuente de verdad del rol sigue siendo la tabla `usuario` (ver sesion.py); esto solo mantiene
                # coherente lo que Keycloak muestra.
                try:
                    rep = http.get(f"{admin}/roles/{rol}", headers=cab)
                    rep.raise_for_status()
                    http.post(f"{admin}/users/{sub}/role-mappings/realm", headers=cab, json=[rep.json()]).raise_for_status()
                except Exception:
                    # Sin el rol la cuenta queda a medias: se retira para no dejar un usuario huérfano en Keycloak
                    # (un ROLLBACK de la base no puede deshacer lo que ya ocurrió en el proveedor externo).
                    http.delete(f"{admin}/users/{sub}", headers=cab)
                    raise
                return sub
        except HTTPException:
            # El 409 de arriba ya es un error con el código correcto: se deja pasar tal cual.
            raise
        except (httpx.HTTPError, KeyError):
            # Cualquier otra falla (red caída, timeout, 401/500 de Keycloak, falta la cabecera Location) no es culpa
            # de la solicitud: 503 para que quien llama pueda reintentar. alta.py hace ROLLBACK de la base.
            raise HTTPException(503, "No se pudo crear el usuario en el proveedor de identidad, intenta de nuevo")

    def eliminar_usuario(self, sub: str) -> None:
        """Compensación: retira un usuario que no llegó a tener fila en la base. No lanza: es mejor esfuerzo."""
        # Se usa desde alta.py solo si algo falla DESPUÉS de crear la cuenta. Si esto también falla, se ignora:
        # peor sería ocultar el error original con otro. Una cuenta huérfana no puede entrar (sin fila → 401).
        try:
            with httpx.Client(timeout=5) as http:
                http.delete(f"{self.base}/admin/realms/{REALM}/users/{sub}", headers=self._cabecera_admin(http))
        except Exception:
            pass


def keycloak_admin() -> KeycloakAdmin:
    """Dependencia de FastAPI; las pruebas la sustituyen por un doble para no necesitar Keycloak.

    alta.py la pide con `Depends(keycloak_admin)`. En producción FastAPI llama a esta función en cada solicitud y
    entrega un cliente real. En las pruebas (tests/conftest.py) se reemplaza con `dependency_overrides` por un objeto
    con los mismos métodos que anota lo que le piden en vez de hablar con Keycloak.
    """
    return KeycloakAdmin.desde_entorno()
