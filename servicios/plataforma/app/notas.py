"""RF15: adjuntar una nota clínica a una cita atendida. Solo la escribe el profesional que atendió esa cita.

QUÉ RUTA CUMPLE CADA PARTE:
  - «adjuntar una nota a una cita atendida» → PUT /citas/{id}/nota (`guardar_nota`): crea la nota o reemplaza su
    contenido (a lo más una por cita, lo garantiza el UNIQUE de `nota_clinica.cita_id`).
  - «solo la escribe el profesional que atendió esa cita» → `solo_profesional` (rol) y la consulta de `_cita_propia`
    (la cita debe ser de un `profesional` cuyo `usuario_id` es el de la sesión).
  - (para armar la pantalla) GET /citas/{id}/nota; la lectura también está restringida a ese profesional.
  - Matriz de permisos: «Nota clínica: solo el profesional, de citas propias»; administrador, recepción y plataforma
    reciben 403. La matriz es mínima y no los deja leerla.

Una cita de otro profesional o de otra clínica responde 404, igual que una inexistente: no se revela que existe (I5).
El estado se valida con la cita ya ATENDIDA; como ATENDIDA es final (RF13), no puede cambiar a mitad de la operación.

Bitácora (RF18): leer y escribir una nota insertan una fila (recurso NOTA_CLINICA) en la MISMA transacción.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from medicitas_comun import CONEXION, Sesion, sesion_de_clinica

from .esquemas import DatosNota, Nota

router = APIRouter(prefix="/citas", tags=["RF15 · Nota clínica"])

_ERRORES = {
    401: {"description": "Sin token válido"},
    403: {"description": "El rol no es profesional"},
    404: {"description": "La cita no existe o no es de este profesional"},
}


def solo_profesional(sesion: Sesion = Depends(sesion_de_clinica)) -> Sesion:
    if sesion.rol != "PROFESIONAL":
        raise HTTPException(403, "Solo el profesional que atendió la cita accede a su nota clínica")
    return sesion


def _cita_propia(con, sesion: Sesion, cita_id: UUID) -> dict:
    fila = con.execute(
        """SELECT c.id, c.paciente_id, c.estado
           FROM cita c JOIN profesional p ON p.clinica_id = c.clinica_id AND p.id = c.profesional_id
           WHERE c.id = %s AND c.clinica_id = %s AND p.usuario_id = %s""",
        (cita_id, sesion.clinica_id, sesion.usuario_id),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Cita no encontrada")
    return fila


def _auditar(con, sesion: Sesion, paciente_id: UUID, accion: str) -> None:
    con.execute(
        """INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso)
           VALUES (%s, %s, %s, %s, 'NOTA_CLINICA')""",
        (sesion.clinica_id, sesion.usuario_id, paciente_id, accion),
    )


_COLUMNAS = "id, cita_id, contenido, creada_en, actualizada_en"


@router.get("/{cita_id}/nota", response_model=Nota,
            responses={**_ERRORES, 404: {"description": "La cita no es de este profesional o aún no tiene nota"}})
def ver_nota(cita_id: UUID, sesion: Sesion = Depends(solo_profesional), con=CONEXION):
    """Lee la nota de una cita propia. Cada lectura queda en la bitácora (RF18)."""
    cita = _cita_propia(con, sesion, cita_id)
    nota = con.execute(f"SELECT {_COLUMNAS} FROM nota_clinica WHERE cita_id = %s AND clinica_id = %s",
                       (cita_id, sesion.clinica_id)).fetchone()
    if nota is None:
        raise HTTPException(404, "Esta cita todavía no tiene nota")
    _auditar(con, sesion, cita["paciente_id"], "LECTURA")
    return nota


@router.put("/{cita_id}/nota", response_model=Nota,
            responses={**_ERRORES, 409: {"description": "La cita no está atendida"}, 422: {"description": "Nota vacía o demasiado larga"}})
def guardar_nota(cita_id: UUID, datos: DatosNota, sesion: Sesion = Depends(solo_profesional), con=CONEXION):
    """Crea la nota de la cita o reemplaza su contenido. Solo sobre citas ATENDIDAS. Queda en la bitácora (RF18)."""
    cita = _cita_propia(con, sesion, cita_id)
    if cita["estado"] != "ATENDIDA":
        raise HTTPException(409, "Solo se escribe una nota sobre una cita atendida")
    # ON CONFLICT: dos guardados simultáneos no chocan con el UNIQUE; el último gana.
    nota = con.execute(
        f"""INSERT INTO nota_clinica (clinica_id, cita_id, contenido) VALUES (%s, %s, %s)
            ON CONFLICT (cita_id) DO UPDATE SET contenido = EXCLUDED.contenido, actualizada_en = now()
            RETURNING {_COLUMNAS}""",
        (sesion.clinica_id, cita_id, datos.contenido),
    ).fetchone()
    _auditar(con, sesion, cita["paciente_id"], "ESCRITURA")
    return nota
