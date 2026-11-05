"""Quién hace la solicitud: usuario, clínica y rol.

Esta es la ÚNICA puerta por la que las rutas saben quién llama. Una ruta recibe `sesion: Sesion = Depends(sesion_actual)`
y toma la clínica de ahí, nunca de un parámetro de la solicitud (I5).

Hoy funciona en modo `desarrollo` (AUTH_MODO=desarrollo): confía en la cabecera X-Usuario-Id y busca al usuario
en la base. NO es seguro, porque cualquiera puede escribir esa cabecera. Cuando exista Keycloak (T17 y T18, de B),
solo cambia el cuerpo de `sesion_actual`: validará el JWT y sacará de él el mismo trío (usuario, clínica, rol).
Las rutas no se enteran.
"""

import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from .app import CONEXION

ROLES = ("ADM_PLATAFORMA", "ADM_CLINICA", "RECEPCION", "PROFESIONAL")


@dataclass(frozen=True)
class Sesion:
    usuario_id: UUID
    clinica_id: UUID | None  # solo el administrador de plataforma no tiene clínica
    rol: str


def sesion_actual(x_usuario_id: str | None = Header(default=None), con=CONEXION) -> Sesion:
    if os.getenv("AUTH_MODO") != "desarrollo":
        # Sin modo de desarrollo y sin JWT todavía: se rechaza todo en vez de dejar pasar a alguien.
        raise HTTPException(401, "Autenticación no configurada")
    try:
        usuario_id = UUID(x_usuario_id or "")
    except ValueError:
        raise HTTPException(401, "No hay sesión iniciada")

    # Se consulta en CADA solicitud, así una baja lógica corta el acceso de inmediato sin esperar a que el
    # token expire (decisión abierta 2 del documento de diseño).
    fila = con.execute(
        "SELECT u.clinica_id, r.codigo AS rol, u.activo FROM usuario u JOIN rol r ON r.id = u.rol_id WHERE u.id = %s",
        (usuario_id,),
    ).fetchone()
    if fila is None:
        raise HTTPException(401, "Usuario desconocido")
    if not fila["activo"]:
        raise HTTPException(403, "Tu usuario fue dado de baja")
    return Sesion(usuario_id, fila["clinica_id"], fila["rol"])


def sesion_de_clinica(sesion: Sesion = Depends(sesion_actual)) -> Sesion:
    """Como sesion_actual, pero exige pertenecer a una clínica: el administrador de plataforma no ve datos clínicos."""
    if sesion.clinica_id is None:
        raise HTTPException(403, "Este usuario no pertenece a ninguna clínica")
    return sesion
