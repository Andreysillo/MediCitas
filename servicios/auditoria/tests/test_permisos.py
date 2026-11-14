"""T29: la matriz de permisos del enunciado en cada ruta de auditoría, y el 401/403 del token. Motor: permisos.py (servicios/pruebas_comunes).

Las solicitudes son las de test_aislamiento_i5.RUTAS. Un rol que no aparece en la fila recibe 403. RF21 (reportes) no está
en la matriz del enunciado: lo decidimos solo para el administrador de la clínica, como la bitácora.
"""

import pytest
from permisos import SI, comprobar_matriz, comprobar_permisos, probar_token
from test_aislamiento_i5 import RUTAS

MATRIZ = {
    "GET /bitacora": dict(admin=SI),                              # Bitácora de auditoría (RF19)
    "GET /reportes/citas-por-estado": dict(admin=SI),
}


def test_cada_ruta_tiene_su_fila_en_la_matriz():
    comprobar_matriz(RUTAS, MATRIZ)


@pytest.mark.parametrize("ruta", MATRIZ)
def test_cada_rol_recibe_lo_que_dice_la_matriz_RF17(cliente, con, ruta):
    comprobar_permisos(cliente, con, ruta, RUTAS[ruta], MATRIZ[ruta])


def test_sin_token_valido_401_y_sin_el_rol_403_RF17(cliente, con, monkeypatch):
    probar_token(cliente, con, monkeypatch, "/bitacora", permitido="admin", negado="recepcion")
