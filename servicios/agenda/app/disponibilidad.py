"""RF7 y RF8: espacios disponibles de un profesional en una fecha, y de un servicio en un rango de fechas."""

from collections import defaultdict
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .esquemas import DisponibilidadDeProfesional, EspaciosDelDia
from .espacios import espacios_libres

# Cualquier rol con clínica puede consultar (matriz de permisos); el administrador de plataforma no tiene clínica.
router = APIRouter(tags=["RF7, RF8 · Disponibilidad"])

DIAS_MAXIMOS = 31


def _servicio_y_zona(con, sesion: Sesion, servicio_id: UUID) -> dict:
    """Duración del servicio y zona horaria de la clínica. La clínica sale de la sesión (I5): un servicio de otra
    clínica responde 404 igual que uno inexistente."""
    fila = con.execute(
        """SELECT s.duracion_minutos, c.zona_horaria
             FROM servicio s JOIN clinica c ON c.id = s.clinica_id
            WHERE s.id = %s AND s.clinica_id = %s AND s.activo""",
        (servicio_id, sesion.clinica_id),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Servicio no encontrado")
    return fila


@router.get("/profesionales/{profesional_id}/disponibilidad", response_model=EspaciosDelDia)
def disponibilidad_de_profesional(
    profesional_id: UUID,
    servicio_id: UUID,
    fecha: date,
    ignorar_cita: UUID | None = None,
    sesion: Sesion = Depends(sesion_de_clinica),
    con=CONEXION,
):
    """RF7: a qué horas puede empezar una cita de ese servicio con ese profesional, en esa fecha (hora local de la clínica)."""
    servicio = _servicio_y_zona(con, sesion, servicio_id)
    profesional = con.execute(
        """SELECT EXISTS (SELECT 1 FROM profesional_servicio ps
                           WHERE ps.clinica_id = p.clinica_id AND ps.profesional_id = p.id
                             AND ps.servicio_id = %s AND ps.activo) AS atiende
             FROM profesional p WHERE p.id = %s AND p.clinica_id = %s AND p.activo""",
        (servicio_id, profesional_id, sesion.clinica_id),
    ).fetchone()
    if profesional is None:
        raise HTTPException(404, "Profesional no encontrado")
    if not profesional["atiende"]:
        # Reservarlo igual fallaría por la clave foránea hacia profesional_servicio (RF4): se avisa antes.
        raise HTTPException(422, "Ese profesional no atiende ese servicio")

    filas = espacios_libres(
        con, clinica_id=sesion.clinica_id, servicio_id=servicio_id, zona_horaria=servicio["zona_horaria"],
        duracion_minutos=servicio["duracion_minutos"], desde=fecha, dias=1, profesional_id=profesional_id,
        ignorar_cita=ignorar_cita,
    )
    return {
        "profesional_id": profesional_id,
        "servicio_id": servicio_id,
        "fecha": fecha,
        "duracion_minutos": servicio["duracion_minutos"],
        "espacios": [f["inicio"] for f in filas],
    }


@router.get("/servicios/{servicio_id}/disponibilidad", response_model=list[DisponibilidadDeProfesional])
def disponibilidad_de_servicio(
    servicio_id: UUID,
    desde: date,
    dias: int = Query(7, ge=1, le=DIAS_MAXIMOS),
    ignorar_cita: UUID | None = None,
    sesion: Sesion = Depends(sesion_de_clinica),
    con=CONEXION,
):
    """RF8: los profesionales que tienen espacio para ese servicio en el rango, y cuáles son.

    Solo aparecen los que tienen al menos un espacio; de cada uno se devuelven todos los días del rango (los sin
    espacio, con la lista vacía), para que quien dibuja el calendario no tenga que rellenar huecos.
    """
    servicio = _servicio_y_zona(con, sesion, servicio_id)
    filas = espacios_libres(
        con, clinica_id=sesion.clinica_id, servicio_id=servicio_id, zona_horaria=servicio["zona_horaria"],
        duracion_minutos=servicio["duracion_minutos"], desde=desde, dias=dias, ignorar_cita=ignorar_cita,
    )
    if not filas:
        return []

    por_profesional: dict[UUID, dict[date, list]] = defaultdict(lambda: defaultdict(list))
    for f in filas:
        por_profesional[f["profesional_id"]][f["fecha"]].append(f["inicio"])

    profesionales = con.execute(
        """SELECT p.id, u.nombre, e.nombre AS especialidad
             FROM profesional p
             JOIN usuario u      ON u.clinica_id = p.clinica_id AND u.id = p.usuario_id
             JOIN especialidad e ON e.clinica_id = p.clinica_id AND e.id = p.especialidad_id
            WHERE p.clinica_id = %s AND p.id = ANY(%s)
            ORDER BY u.nombre""",
        (sesion.clinica_id, list(por_profesional)),
    ).fetchall()

    fechas = [desde.fromordinal(desde.toordinal() + i) for i in range(dias)]
    return [
        {"profesional": p, "dias": [{"fecha": d, "espacios": por_profesional[p["id"]].get(d, [])} for d in fechas]}
        for p in profesionales
    ]
