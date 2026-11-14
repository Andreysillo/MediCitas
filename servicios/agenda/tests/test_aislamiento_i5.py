"""T26: I5 en TODAS las rutas de agenda, con intentos deliberados de fuga. El motor está en aislamiento.py (servicios/pruebas_comunes).

Cada entrada dice cómo se arma la solicitud a partir de dos clínicas: `w` es la clínica de lo que la ruta toca (los ids
del camino) y `ref` la de lo que se menciona (consulta y cuerpo). El barrido las combina: todo ajeno, camino propio con
referencias ajenas y al revés. Una ruta nueva que no esté aquí hace fallar test_todas_las_rutas_estan_en_el_barrido.
"""

from datetime import timedelta

import pytest
from aislamiento import Barrido, comprobar_cobertura

from app.main import app

RUTAS = {
    "GET /profesionales": lambda w, ref: dict(url="/profesionales"),
    "GET /profesionales/{profesional_id}/horarios": lambda w, ref: dict(url=f"/profesionales/{w.prof}/horarios"),
    "POST /profesionales/{profesional_id}/horarios": lambda w, ref: dict(
        url=f"/profesionales/{w.prof}/horarios", json=dict(dia_semana=1, hora_inicio="13:00", hora_fin="14:00")),
    "DELETE /horarios/{horario_id}": lambda w, ref: dict(url=f"/horarios/{w.horario}"),
    "GET /profesionales/{profesional_id}/bloqueos": lambda w, ref: dict(url=f"/profesionales/{w.prof}/bloqueos"),
    "POST /profesionales/{profesional_id}/bloqueos": lambda w, ref: dict(
        url=f"/profesionales/{w.prof}/bloqueos",
        json=dict(inicio=ref.inicio_libre + timedelta(hours=2), fin=ref.inicio_libre + timedelta(hours=2, minutes=30), motivo="Congreso")),
    "DELETE /bloqueos/{bloqueo_id}": lambda w, ref: dict(url=f"/bloqueos/{w.bloqueo}"),
    "GET /profesionales/{profesional_id}/disponibilidad": lambda w, ref: dict(
        url=f"/profesionales/{w.prof}/disponibilidad", params=dict(servicio_id=ref.servicio, fecha=ref.fecha, ignorar_cita=ref.cita)),
    "GET /servicios/{servicio_id}/disponibilidad": lambda w, ref: dict(
        url=f"/servicios/{w.servicio}/disponibilidad", params=dict(desde=ref.fecha, ignorar_cita=ref.cita)),
    "GET /agenda": lambda w, ref: dict(url="/agenda", params=dict(fecha=ref.fecha, profesional_id=ref.prof)),
    "POST /citas": lambda w, ref: dict(url="/citas", json=dict(
        paciente_id=ref.paciente, profesional_id=ref.prof, servicio_id=ref.servicio, inicio=ref.inicio_libre)),
    "POST /citas/{cita_id}/reprogramar": lambda w, ref: dict(
        url=f"/citas/{w.cita}/reprogramar", json=dict(profesional_id=ref.prof, inicio=ref.inicio_libre)),
    "POST /citas/{cita_id}/cancelar": lambda w, ref: dict(url=f"/citas/{w.cita}/cancelar", json=dict(motivo="No puede venir")),
    "POST /citas/{cita_id}/desenlace": lambda w, ref: dict(url=f"/citas/{w.cita_pasada}/desenlace", json=dict(desenlace="ATENDIDA")),
}


def test_todas_las_rutas_estan_en_el_barrido():
    comprobar_cobertura(app, RUTAS)


@pytest.mark.parametrize("ruta", RUTAS)
def test_ninguna_ruta_deja_ver_ni_tocar_otra_clinica_I5(cliente, con, ruta):
    Barrido(cliente, con, ruta, RUTAS[ruta]).correr()
