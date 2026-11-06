"""Quién hace la solicitud: usuario, clínica y rol.

Esta es la ÚNICA puerta por la que las rutas saben quién llama. Una ruta recibe `sesion: Sesion = Depends(sesion_actual)`
y toma la clínica de ahí, nunca de un parámetro de la solicitud (I5).

Dos modos, elegidos por AUTH_MODO (variable del compose):

- "keycloak" (por defecto): RF17. Valida el JWT del encabezado Authorization contra las llaves públicas del
  realm y busca al usuario por `keycloak_sub = token["sub"]`. No se implementa el inicio de sesión: eso lo
  hace Keycloak, aquí solo se verifica lo que firmó.
- "desarrollo": confía en la cabecera X-Usuario-Id, SIN validar. Solo para desarrollar sin levantar Keycloak
  y para las pruebas (tests/conftest.py lo fija con os.environ.setdefault). NO es segura: cualquiera puede
  escribir esa cabecera.

Con cualquier otro valor (o sin configurar) todo se rechaza con 401 en vez de dejar pasar a alguien. Las
rutas no se enteran de cuál de los dos modos está activo: siempre reciben el mismo `Sesion`.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from .app import CONEXION


@dataclass(frozen=True)
class Sesion:
    usuario_id: UUID
    clinica_id: UUID | None  # solo el administrador de plataforma no tiene clínica
    rol: str


@lru_cache
def _cliente_jwks() -> PyJWKClient:
    """Un cliente por proceso: PyJWKClient cachea las llaves públicas del realm y solo vuelve a pedirlas al
    JWKS si aparece un `kid` que no conoce (por ejemplo, tras rotar las llaves). KEYCLOAK_JWKS_URL es la dirección
    INTERNA del compose; KEYCLOAK_ISSUER, la pública que viene en el token. timeout: esto corre con una conexión
    del pool tomada, así que un Keycloak caído no debe retenerla los 30 s por defecto."""
    return PyJWKClient(os.environ["KEYCLOAK_JWKS_URL"], timeout=3)


def _sub_del_token(autorizacion: str | None) -> str:
    """Valida firma, emisor y expiración del JWT contra las llaves públicas del realm, y devuelve su `sub`.

    No se exige `aud`: el realm es exclusivo de MediCitas (lo versiona este repositorio), así que cualquier
    token que el realm firme proviene de uno de sus propios clients; no hay otra audiencia de la que
    protegerse. Es una decisión documentada, no un descuido (ver docs/diseno-modelo-logico.md, «Identidad
    delegada»); si el realm llegara a compartirse con otra aplicación, aquí es donde se agregaría la
    validación de `aud` o `azp`.
    """
    if not autorizacion or not autorizacion.lower().startswith("bearer "):
        raise HTTPException(401, "Falta el token de acceso")
    token = autorizacion[len("bearer "):].strip()
    try:
        llave = _cliente_jwks().get_signing_key_from_jwt(token)
        datos = jwt.decode(
            token,
            llave.key,
            algorithms=["RS256"],
            issuer=os.environ["KEYCLOAK_ISSUER"],
            options={"verify_aud": False},
        )
    except PyJWKClientConnectionError:
        # No es culpa del cliente: el token puede ser válido, pero no se pudo comprobar.
        raise HTTPException(503, "No se pudo validar el token, intenta de nuevo")
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Token inválido: {e}")
    # El id_token lleva la misma firma y el mismo emisor, pero dice quién inició sesión, no qué puede hacer.
    if datos.get("typ") != "Bearer":
        raise HTTPException(401, "Se esperaba un token de acceso")
    sub = datos.get("sub")
    if not sub:
        raise HTTPException(401, "El token no trae identificador de usuario")
    return sub


_CONSULTA = "SELECT u.id, u.clinica_id, r.codigo AS rol, u.activo FROM usuario u JOIN rol r ON r.id = u.rol_id WHERE u.{} = %s"


def sesion_actual(
    authorization: str | None = Header(default=None),
    x_usuario_id: str | None = Header(default=None, alias="X-Usuario-Id"),
    con=CONEXION,
) -> Sesion:
    modo = os.getenv("AUTH_MODO")

    if modo == "keycloak":
        fila = con.execute(_CONSULTA.format("keycloak_sub"), (_sub_del_token(authorization),)).fetchone()
    elif modo == "desarrollo":
        try:
            usuario_id = UUID(x_usuario_id or "")
        except ValueError:
            raise HTTPException(401, "No hay sesión iniciada")
        fila = con.execute(_CONSULTA.format("id"), (usuario_id,)).fetchone()
    else:
        # Ni "keycloak" ni "desarrollo": se rechaza todo en vez de dejar pasar a alguien.
        raise HTTPException(401, "Autenticación no configurada")

    # Se consulta en CADA solicitud, así una baja lógica corta el acceso de inmediato sin esperar a que el
    # token expire (decisión abierta 2 del documento de diseño, ya resuelta en ese sentido).
    if fila is None:
        raise HTTPException(401, "Usuario desconocido")
    if not fila["activo"]:
        raise HTTPException(403, "Tu usuario fue dado de baja")
    return Sesion(fila["id"], fila["clinica_id"], fila["rol"])


def sesion_de_clinica(sesion: Sesion = Depends(sesion_actual)) -> Sesion:
    """Como sesion_actual, pero exige pertenecer a una clínica: el administrador de plataforma no ve datos clínicos."""
    if sesion.clinica_id is None:
        raise HTTPException(403, "Este usuario no pertenece a ninguna clínica")
    return sesion
