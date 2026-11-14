"""T29: la matriz de permisos del enunciado en cada ruta de plataforma, y el 401/403 del token. Motor: permisos.py (servicios/pruebas_comunes).

Las solicitudes son las de test_aislamiento_i5.RUTAS. Un rol que no aparece en la fila recibe 403.
"""

import pytest
from permisos import PROPIOS, SI, comprobar_matriz, comprobar_permisos, probar_token
from test_aislamiento_i5 import RUTAS

PLATAFORMA = dict(plataforma=SI)                                  # Alta de clínicas (RF1)
ADMIN = dict(admin=SI)                                            # Usuarios, servicios y profesionales (RF2 a RF4)
LEEN = dict(admin=SI, recepcion=SI, profesional=SI)               # Pacientes: el profesional solo lee (RF14); historial (RF16)
ESCRIBEN = dict(admin=SI, recepcion=SI)
NOTA = dict(profesional=PROPIOS)                                  # Nota clínica, solo de citas propias (RF15)

MATRIZ = {
    "POST /clinicas": PLATAFORMA,
    "GET /clinicas": PLATAFORMA,
    "GET /usuarios": ADMIN,
    "POST /usuarios": ADMIN,
    "PATCH /usuarios/{usuario_id}/rol": ADMIN,
    "PATCH /usuarios/{usuario_id}/activo": ADMIN,
    "GET /especialidades": ADMIN,
    "POST /especialidades": ADMIN,
    "GET /servicios": ADMIN,
    "POST /servicios": ADMIN,
    "PATCH /servicios/{servicio_id}": ADMIN,
    "GET /profesionales": ADMIN,
    "GET /profesionales/usuarios-libres": ADMIN,
    "POST /profesionales": ADMIN,
    "PUT /profesionales/{profesional_id}": ADMIN,
    "GET /pacientes": LEEN,
    "GET /pacientes/{paciente_id}": LEEN,
    "GET /pacientes/{paciente_id}/historial": LEEN,
    "POST /pacientes": ESCRIBEN,
    "PUT /pacientes/{paciente_id}": ESCRIBEN,
    "GET /citas/{cita_id}/nota": NOTA,
    "PUT /citas/{cita_id}/nota": NOTA,
}


def test_cada_ruta_tiene_su_fila_en_la_matriz():
    comprobar_matriz(RUTAS, MATRIZ)


@pytest.mark.parametrize("ruta", MATRIZ)
def test_cada_rol_recibe_lo_que_dice_la_matriz_RF17(cliente, con, ruta):
    comprobar_permisos(cliente, con, ruta, RUTAS[ruta], MATRIZ[ruta])


def test_sin_token_valido_401_y_sin_el_rol_403_RF17(cliente, con, monkeypatch):
    probar_token(cliente, con, monkeypatch, "/usuarios", permitido="admin", negado="recepcion")
