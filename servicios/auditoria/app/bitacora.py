"""RF19: consulta de la bitácora, solo para el administrador de la clínica, con filtros por usuario, paciente y fechas.

Esta ruta solo lee. Que nadie pueda modificar ni borrar la bitácora (I6) lo impone el motor, no este archivo.
"""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from medicitas_comun import CONEXION, Sesion
from pydantic import BaseModel

from .permisos import admin_de_clinica

router = APIRouter(tags=["RF19 · Bitácora"])

LIMITE = 100


class Registro(BaseModel):
    id: int
    ocurrido_en: datetime
    usuario_id: UUID
    usuario: str
    rol: str
    accion: str
    recurso: str
    paciente_id: UUID
    paciente: str
    identificacion: str


class ListaRegistros(BaseModel):
    total: int
    registros: list[Registro]


@router.get("/bitacora", response_model=ListaRegistros, responses={
    403: {"description": "Solo el administrador de clínica"}, 422: {"description": "Filtros inválidos"}})
def consultar_bitacora(
    usuario_id: UUID | None = None,
    paciente: str = Query("", max_length=80, description="Texto en el nombre o la identificación del paciente"),
    desde: date | None = Query(None, description="Día local de la clínica, incluido"),
    hasta: date | None = Query(None, description="Día local de la clínica, incluido"),
    sesion: Sesion = Depends(admin_de_clinica),
    con=CONEXION,
):
    """Registros más recientes primero: los primeros 100 y el total que cumple los filtros."""
    if desde and hasta and desde > hasta:
        raise HTTPException(422, "La fecha inicial no puede ser posterior a la final")

    patron = "%" + paciente.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    # Los días se interpretan en la zona de la clínica. La clínica sale de la sesión (I5); los JOIN también la llevan.
    donde = """r.clinica_id = %(clinica)s
               AND (%(usuario)s::uuid IS NULL OR r.usuario_id = %(usuario)s)
               AND (pa.nombre ILIKE %(patron)s OR pa.identificacion ILIKE %(patron)s)
               AND (%(desde)s::date IS NULL OR r.ocurrido_en >= (%(desde)s::date)::timestamp AT TIME ZONE cl.zona_horaria)
               AND (%(hasta)s::date IS NULL OR r.ocurrido_en < ((%(hasta)s::date + 1)::timestamp AT TIME ZONE cl.zona_horaria))"""
    desde_sql = """FROM registro_auditoria r
                   JOIN clinica cl  ON cl.id = r.clinica_id
                   JOIN usuario u   ON u.clinica_id = r.clinica_id AND u.id = r.usuario_id
                   JOIN rol ro      ON ro.id = u.rol_id
                   JOIN paciente pa ON pa.clinica_id = r.clinica_id AND pa.id = r.paciente_id"""
    params = {"clinica": sesion.clinica_id, "usuario": usuario_id, "patron": patron, "desde": desde, "hasta": hasta}

    total = con.execute(f"SELECT count(*) AS n {desde_sql} WHERE {donde}", params).fetchone()["n"]
    filas = con.execute(
        f"""SELECT r.id, r.ocurrido_en, r.usuario_id, u.nombre AS usuario, ro.codigo AS rol, r.accion, r.recurso,
                   r.paciente_id, pa.nombre AS paciente, pa.identificacion
            {desde_sql} WHERE {donde}
            ORDER BY r.ocurrido_en DESC, r.id DESC LIMIT {LIMITE}""",
        params,
    ).fetchall()
    return {"total": total, "registros": filas}
