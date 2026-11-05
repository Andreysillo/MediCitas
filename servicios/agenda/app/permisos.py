"""Quién puede tocar los horarios y bloqueos de quién (matriz de permisos del enunciado)."""

from uuid import UUID

from fastapi import Depends, HTTPException
from medicitas_comun import Sesion, sesion_de_clinica


def puede_gestionar(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    """Administrador de clínica: todos los profesionales. Profesional: solo el suyo. Recepción: ninguno."""
    if sesion.rol not in ("ADM_CLINICA", "PROFESIONAL"):
        raise HTTPException(403, "Tu rol no gestiona horarios ni bloqueos")
    return sesion


def profesional_accesible(con, sesion: Sesion, profesional_id: UUID, *, bloquear: bool = False) -> dict:
    """Devuelve al profesional si quien consulta puede gestionarlo; si no, 404.

    La clínica sale de la sesión, nunca de la solicitud (I5). Un profesional de otra clínica, o uno que no es
    el propio, responde 404 igual que uno inexistente: no se revela que existe.

    bloquear=True toma un bloqueo de fila sobre el profesional, para los cambios que pueden dejar citas fuera
    de su agenda (un bloqueo nuevo, quitar un bloque de horario). La reserva (RF9) toma el MISMO bloqueo
    (ver reserva.py), así que o la reserva entra antes y el cambio la lista como conflicto, o entra después y
    ya ve el cambio: nunca queda una cita colada. NO KEY UPDATE (y no UPDATE) para no frenar la verificación
    de las claves foráneas de otras inserciones.
    """
    sql = "SELECT id, clinica_id, usuario_id FROM profesional WHERE id = %s AND clinica_id = %s AND activo"
    params = [profesional_id, sesion.clinica_id]
    if sesion.rol == "PROFESIONAL":
        sql += " AND usuario_id = %s"
        params.append(sesion.usuario_id)
    if bloquear:
        sql += " FOR NO KEY UPDATE"
    fila = con.execute(sql, params).fetchone()
    if fila is None:
        raise HTTPException(404, "Profesional no encontrado")
    return fila
