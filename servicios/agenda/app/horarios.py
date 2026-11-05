"""RF5: horario de atención semanal de cada profesional, con varios bloques por día (jornada partida)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import Sesion, conexion

from . import conflictos
from .esquemas import Horario, HorarioEliminado, NuevoHorario, ProfesionalResumen
from .permisos import profesional_accesible, puede_gestionar

router = APIRouter(tags=["RF5 · Horarios"])

# Las horas salen como "08:00": la columna es `time` y sin to_char saldría "08:00:00".
_COLUMNAS = "id, profesional_id, dia_semana, to_char(hora_inicio, 'HH24:MI') AS hora_inicio, to_char(hora_fin, 'HH24:MI') AS hora_fin"


@router.get("/profesionales", response_model=list[ProfesionalResumen])
def profesionales_gestionables(sesion: Sesion = Depends(puede_gestionar), con=Depends(conexion)):
    """Los profesionales cuyo horario puede gestionar quien consulta: todos los de su clínica, o solo él mismo."""
    return con.execute(
        """SELECT p.id, u.nombre, e.nombre AS especialidad
             FROM profesional p
             JOIN usuario u      ON u.clinica_id = p.clinica_id AND u.id = p.usuario_id
             JOIN especialidad e ON e.clinica_id = p.clinica_id AND e.id = p.especialidad_id
            WHERE p.clinica_id = %s AND p.activo AND (%s <> 'PROFESIONAL' OR p.usuario_id = %s)
            ORDER BY u.nombre""",
        (sesion.clinica_id, sesion.rol, sesion.usuario_id),
    ).fetchall()


@router.get("/profesionales/{profesional_id}/horarios", response_model=list[Horario])
def listar_horarios(profesional_id: UUID, sesion: Sesion = Depends(puede_gestionar), con=Depends(conexion)):
    profesional_accesible(con, sesion, profesional_id)
    return con.execute(
        f"SELECT {_COLUMNAS} FROM horario_atencion WHERE profesional_id = %s ORDER BY dia_semana, hora_inicio",
        (profesional_id,),
    ).fetchall()


@router.post("/profesionales/{profesional_id}/horarios", response_model=Horario, status_code=201)
def crear_horario(profesional_id: UUID, nuevo: NuevoHorario, sesion: Sesion = Depends(puede_gestionar), con=Depends(conexion)):
    """Agrega un bloque. Un mismo día puede tener varios, pero no solapados.

    No se revisa el solape aquí: lo rechaza la restricción `horario_sin_solape` del motor (409). Revisarlo antes
    con un SELECT dejaría una ventana en la que dos solicitudes simultáneas pasan la revisión y se solapan.
    """
    profesional_accesible(con, sesion, profesional_id)
    return con.execute(
        f"""INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
            VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNAS}""",
        (sesion.clinica_id, profesional_id, nuevo.dia_semana, nuevo.hora_inicio, nuevo.hora_fin),
    ).fetchone()


@router.delete("/horarios/{horario_id}", response_model=HorarioEliminado)
def eliminar_horario(horario_id: UUID, sesion: Sesion = Depends(puede_gestionar), con=Depends(conexion)):
    """Quita un bloque. Rige hacia adelante: no cancela citas, pero devuelve las reservas que quedaron fuera
    de toda atención (I3) para que recepción las reprograme."""
    fila = con.execute(
        "SELECT profesional_id FROM horario_atencion WHERE id = %s AND clinica_id = %s", (horario_id, sesion.clinica_id)
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Horario no encontrado")
    # El bloqueo va ANTES de borrar y de calcular los conflictos; ver profesional_accesible.
    profesional_accesible(con, sesion, fila["profesional_id"], bloquear=True)
    con.execute("DELETE FROM horario_atencion WHERE id = %s", (horario_id,))
    return {"conflictos": conflictos.fuera_de_horario(con, sesion.clinica_id, fila["profesional_id"])}
