"""T26: I5 en TODAS las rutas de plataforma, con intentos deliberados de fuga. El motor está en aislamiento.py (servicios/pruebas_comunes).

Cada entrada dice cómo se arma la solicitud a partir de dos clínicas: `w` es la clínica de lo que la ruta toca (los ids
del camino) y `ref` la de lo que se menciona (consulta y cuerpo). Una ruta nueva que no esté aquí hace fallar
test_todas_las_rutas_estan_en_el_barrido.
"""

import pytest
from aislamiento import Barrido, comprobar_cobertura, unico

from app.main import app

CONTRASENA = "temporal-123"
PACIENTE = lambda: dict(identificacion=unico(), nombre="Paciente Nuevo", fecha_nacimiento="1990-01-01")

RUTAS = {
    "POST /clinicas": lambda w, ref: dict(url="/clinicas", json=dict(
        nombre="Clínica Nueva", identificador=unico(), zona_horaria="America/Costa_Rica",
        admin_nombre="Admin Nuevo", admin_usuario=unico(), admin_contrasena=CONTRASENA)),
    "GET /clinicas": lambda w, ref: dict(url="/clinicas"),
    "GET /usuarios": lambda w, ref: dict(url="/usuarios"),
    "POST /usuarios": lambda w, ref: dict(url="/usuarios", json=dict(nombre="Usuario Nuevo", rol="RECEPCION", usuario=unico(), contrasena=CONTRASENA)),
    "PATCH /usuarios/{usuario_id}/rol": lambda w, ref: dict(url=f"/usuarios/{w.recepcion}/rol", json=dict(rol="ADM_CLINICA")),
    "PATCH /usuarios/{usuario_id}/activo": lambda w, ref: dict(url=f"/usuarios/{w.recepcion}/activo", json=dict(activo=False)),
    "GET /especialidades": lambda w, ref: dict(url="/especialidades"),
    "POST /especialidades": lambda w, ref: dict(url="/especialidades", json=dict(nombre=unico())),
    "GET /servicios": lambda w, ref: dict(url="/servicios"),
    "POST /servicios": lambda w, ref: dict(url="/servicios", json=dict(nombre=unico(), duracion_minutos=30, especialidad_id=ref.especialidad)),
    "PATCH /servicios/{servicio_id}": lambda w, ref: dict(url=f"/servicios/{w.servicio}", json=dict(nombre=unico(), duracion_minutos=30, activo=True)),
    "GET /profesionales": lambda w, ref: dict(url="/profesionales"),
    "GET /profesionales/usuarios-libres": lambda w, ref: dict(url="/profesionales/usuarios-libres"),
    "POST /profesionales": lambda w, ref: dict(url="/profesionales", json=dict(
        usuario_id=ref.usuario_libre, especialidad_id=ref.especialidad, numero_colegiado="COL-99", servicios_ids=[ref.servicio])),
    "PUT /profesionales/{profesional_id}": lambda w, ref: dict(url=f"/profesionales/{w.prof}", json=dict(
        especialidad_id=ref.especialidad, numero_colegiado="COL-99", servicios_ids=[ref.servicio])),
    # Buscar por la identificación de un paciente ajeno: el texto también es un intento de fuga, no solo los ids.
    "GET /pacientes": lambda w, ref: dict(url="/pacientes", params=dict(q=ref.identificacion)),
    "POST /pacientes": lambda w, ref: dict(url="/pacientes", json=PACIENTE()),
    "GET /pacientes/{paciente_id}": lambda w, ref: dict(url=f"/pacientes/{w.paciente}"),
    "PUT /pacientes/{paciente_id}": lambda w, ref: dict(url=f"/pacientes/{w.paciente}", json=PACIENTE()),
    "GET /pacientes/{paciente_id}/historial": lambda w, ref: dict(url=f"/pacientes/{w.paciente}/historial"),
    "GET /citas/{cita_id}/nota": lambda w, ref: dict(url=f"/citas/{w.cita_atendida}/nota"),
    "PUT /citas/{cita_id}/nota": lambda w, ref: dict(url=f"/citas/{w.cita_atendida}/nota", json=dict(contenido="Evolución favorable")),
}


def test_todas_las_rutas_estan_en_el_barrido():
    comprobar_cobertura(app, RUTAS)


@pytest.mark.parametrize("ruta", RUTAS)
def test_ninguna_ruta_deja_ver_ni_tocar_otra_clinica_I5(cliente, con, ruta):
    Barrido(cliente, con, ruta, RUTAS[ruta]).correr()
