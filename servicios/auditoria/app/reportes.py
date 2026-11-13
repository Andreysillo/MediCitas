"""RF21: contar las citas por estado dentro de un rango de fechas, con una sola consulta agregada."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion
from pydantic import BaseModel

from .permisos import admin_de_clinica

router = APIRouter(tags=["RF21 · Reportes"])

ESTADOS = ("RESERVADA", "ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA")
MAX_DIAS = 366


class CitasPorEstado(BaseModel):
    desde: date
    hasta: date
    total: int
    por_estado: dict[str, int]


@router.get("/reportes/citas-por-estado", response_model=CitasPorEstado, responses={
    403: {"description": "Solo el administrador de clínica"}, 422: {"description": "Rango inválido"}})
def citas_por_estado(desde: date, hasta: date, sesion: Sesion = Depends(admin_de_clinica), con=CONEXION):
    """Cuenta las citas cuyo inicio cae entre `desde` y `hasta`, ambos días locales de la clínica incluidos.
    Todos los estados salen en el resultado, también los que tienen cero."""
    if desde > hasta:
        raise HTTPException(422, "La fecha inicial no puede ser posterior a la final")
    if (hasta - desde).days + 1 > MAX_DIAS:
        raise HTTPException(422, f"El rango no puede pasar de {MAX_DIAS} días")

    filas = con.execute(
        """SELECT c.estado, count(*) AS n
             FROM cita c JOIN clinica cl ON cl.id = c.clinica_id
            WHERE c.clinica_id = %s
              AND c.inicio >= (%s::date)::timestamp AT TIME ZONE cl.zona_horaria
              AND c.inicio <  ((%s::date + 1)::timestamp AT TIME ZONE cl.zona_horaria)
            GROUP BY c.estado""",
        (sesion.clinica_id, desde, hasta),
    ).fetchall()
    por_estado = dict.fromkeys(ESTADOS, 0) | {f["estado"]: f["n"] for f in filas}
    return {"desde": desde, "hasta": hasta, "total": sum(por_estado.values()), "por_estado": por_estado}
