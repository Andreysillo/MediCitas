"""RF20: la agenda del día, de un profesional o de toda la clínica (la vista de recepción)."""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica
from pydantic import BaseModel

router = APIRouter(tags=["RF20 · Agenda del día"])


class CitaDelDia(BaseModel):
    id: UUID
    inicio: datetime
    fin: datetime
    estado: str
    paciente_id: UUID
    paciente: str
    profesional_id: UUID
    profesional: str
    servicio_id: UUID
    servicio: str


@router.get("/agenda", response_model=list[CitaDelDia], responses={404: {"description": "El profesional no existe en tu clínica"}})
def agenda_del_dia(fecha: date, profesional_id: UUID | None = None, sesion: Sesion = Depends(sesion_de_clinica), con=CONEXION):
    """Citas cuyo inicio cae en `fecha` (día local de la clínica), por hora. Sin `profesional_id` trae toda la clínica.

    Un profesional solo ve la suya: si pide otro responde 404. Las REPROGRAMADAS no salen, porque la cita nueva que las
    reemplaza ya aparece en su día; las canceladas sí, con su estado.
    """
    params = {"clinica": sesion.clinica_id, "fecha": fecha, "profesional": profesional_id}
    if sesion.rol == "PROFESIONAL":
        propio = con.execute("SELECT id FROM profesional WHERE clinica_id = %s AND usuario_id = %s",
                             (sesion.clinica_id, sesion.usuario_id)).fetchone()
        if propio is None or (profesional_id and profesional_id != propio["id"]):
            raise HTTPException(404, "Profesional no encontrado")
        params["profesional"] = propio["id"]
    elif profesional_id and con.execute("SELECT 1 FROM profesional WHERE id = %s AND clinica_id = %s",
                                        (profesional_id, sesion.clinica_id)).fetchone() is None:
        raise HTTPException(404, "Profesional no encontrado")

    return con.execute(
        """SELECT c.id, c.inicio, c.fin, c.estado, c.paciente_id, pa.nombre AS paciente,
                  c.profesional_id, u.nombre AS profesional, c.servicio_id, s.nombre AS servicio
             FROM cita c
             JOIN clinica cl    ON cl.id = c.clinica_id
             JOIN paciente pa   ON pa.clinica_id = c.clinica_id AND pa.id = c.paciente_id
             JOIN profesional p ON p.clinica_id = c.clinica_id AND p.id = c.profesional_id
             JOIN usuario u     ON u.clinica_id = p.clinica_id AND u.id = p.usuario_id
             JOIN servicio s    ON s.clinica_id = c.clinica_id AND s.id = c.servicio_id
            WHERE c.clinica_id = %(clinica)s
              AND (%(profesional)s::uuid IS NULL OR c.profesional_id = %(profesional)s)
              AND c.estado <> 'REPROGRAMADA'
              AND c.inicio >= (%(fecha)s::date)::timestamp AT TIME ZONE cl.zona_horaria
              AND c.inicio <  ((%(fecha)s::date + 1)::timestamp AT TIME ZONE cl.zona_horaria)
            ORDER BY c.inicio, u.nombre, c.id""",
        params,
    ).fetchall()
