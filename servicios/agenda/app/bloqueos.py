"""RF6: bloqueos de agenda por vacaciones o permisos."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from medicitas_comun import CONEXION, Sesion

from . import cache, conflictos
from .esquemas import Bloqueo, NuevoBloqueo
from .permisos import profesional_accesible, puede_gestionar

router = APIRouter(tags=["RF6 · Bloqueos"])


@router.get("/profesionales/{profesional_id}/bloqueos", response_model=list[Bloqueo])
def listar_bloqueos(profesional_id: UUID, sesion: Sesion = Depends(puede_gestionar), con=CONEXION):
    """Bloqueos vigentes o futuros, cada uno con las citas reservadas que deja en conflicto."""
    profesional_accesible(con, sesion, profesional_id)
    bloqueos = con.execute(
        """SELECT id, profesional_id, inicio, fin, motivo FROM bloqueo_agenda
            WHERE profesional_id = %s AND fin > now() ORDER BY inicio""",
        (profesional_id,),
    ).fetchall()
    # Una sola consulta de citas para todos los bloqueos, en vez de una por bloqueo.
    citas = conflictos.reservadas_futuras(con, sesion.clinica_id, profesional_id)
    return [{**b, "conflictos": conflictos.en_bloqueo(citas, b["inicio"], b["fin"])} for b in bloqueos]


@router.post("/profesionales/{profesional_id}/bloqueos", response_model=Bloqueo, status_code=201)
def crear_bloqueo(profesional_id: UUID, nuevo: NuevoBloqueo, request: Request, sesion: Sesion = Depends(puede_gestionar), con=CONEXION):
    """Registra el bloqueo. Retira la disponibilidad hacia adelante, pero NO cancela citas: las reservadas
    que caen dentro vuelven en `conflictos` para que recepción las reprograme."""
    if nuevo.fin <= datetime.now(timezone.utc):
        raise HTTPException(422, "El bloqueo ya terminó: no tiene efecto sobre la agenda")
    # El bloqueo de fila va ANTES de insertar y de buscar conflictos: si una reserva entra a la vez, o ya
    # estaba confirmada y aparece en la lista, o espera y encuentra el bloqueo (ver profesional_accesible).
    profesional_accesible(con, sesion, profesional_id, bloquear=True)
    cache.invalidar_tras_commit(request, profesional_id)
    bloqueo = con.execute(
        """INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo)
           VALUES (%s, %s, %s, %s, %s) RETURNING id, profesional_id, inicio, fin, motivo""",
        (sesion.clinica_id, profesional_id, nuevo.inicio, nuevo.fin, nuevo.motivo),
    ).fetchone()
    citas = conflictos.reservadas_futuras(con, sesion.clinica_id, profesional_id)
    return {**bloqueo, "conflictos": conflictos.en_bloqueo(citas, bloqueo["inicio"], bloqueo["fin"])}


@router.delete("/bloqueos/{bloqueo_id}", status_code=204)
def eliminar_bloqueo(bloqueo_id: UUID, request: Request, sesion: Sesion = Depends(puede_gestionar), con=CONEXION):
    fila = con.execute(
        "SELECT profesional_id FROM bloqueo_agenda WHERE id = %s AND clinica_id = %s", (bloqueo_id, sesion.clinica_id)
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Bloqueo no encontrado")
    profesional_accesible(con, sesion, fila["profesional_id"])
    con.execute("DELETE FROM bloqueo_agenda WHERE id = %s", (bloqueo_id,))
    cache.invalidar_tras_commit(request, fila["profesional_id"])
    return Response(status_code=204)
