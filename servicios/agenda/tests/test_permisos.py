"""T29: la matriz de permisos del enunciado en cada ruta de agenda, y el 401/403 del token. Motor: permisos.py (servicios/pruebas_comunes).

Las solicitudes son las de test_aislamiento_i5.RUTAS. Un rol que no aparece en la fila recibe 403. RF20 (agenda del día)
no está en la matriz del enunciado: la decidimos así, y un profesional solo ve la suya.
"""

import pytest
from permisos import PROPIOS, SI, comprobar_matriz, comprobar_permisos, probar_token
from test_aislamiento_i5 import RUTAS

GESTION = dict(admin=SI, profesional=PROPIOS)                     # Horarios y bloqueos (RF5, RF6)
CONSULTA = dict(admin=SI, recepcion=SI, profesional=SI)           # Consultar disponibilidad (RF7, RF8) y desenlace (RF12)
AGENDAR = dict(admin=SI, recepcion=SI)                            # Reservar, reprogramar y cancelar (RF9 a RF11)

MATRIZ = {
    "GET /profesionales": CONSULTA,                                # los que puede ver: el profesional, solo a sí mismo; recepción necesita elegir uno para reservar
    "GET /profesionales/{profesional_id}/horarios": GESTION,
    "POST /profesionales/{profesional_id}/horarios": GESTION,
    "DELETE /horarios/{horario_id}": GESTION,
    "GET /profesionales/{profesional_id}/bloqueos": GESTION,
    "POST /profesionales/{profesional_id}/bloqueos": GESTION,
    "DELETE /bloqueos/{bloqueo_id}": GESTION,
    "GET /profesionales/{profesional_id}/disponibilidad": CONSULTA,
    "GET /servicios/{servicio_id}/disponibilidad": CONSULTA,
    "GET /agenda": dict(admin=SI, recepcion=SI, profesional=PROPIOS),
    "POST /citas": AGENDAR,
    "POST /citas/{cita_id}/reprogramar": AGENDAR,
    "POST /citas/{cita_id}/cancelar": AGENDAR,
    "POST /citas/{cita_id}/desenlace": CONSULTA,
}


def test_cada_ruta_tiene_su_fila_en_la_matriz():
    comprobar_matriz(RUTAS, MATRIZ)


@pytest.mark.parametrize("ruta", MATRIZ)
def test_cada_rol_recibe_lo_que_dice_la_matriz_RF17(cliente, con, ruta):
    comprobar_permisos(cliente, con, ruta, RUTAS[ruta], MATRIZ[ruta])


def test_sin_token_valido_401_y_sin_el_rol_403_RF17(cliente, con, monkeypatch):
    probar_token(cliente, con, monkeypatch, "/profesionales", permitido="admin", negado="plataforma")
