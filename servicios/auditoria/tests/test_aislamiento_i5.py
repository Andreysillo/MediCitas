"""T26: I5 en TODAS las rutas de auditoría, con intentos deliberados de fuga. El motor está en aislamiento.py (servicios/pruebas_comunes).

`w` es la clínica de lo que la ruta toca y `ref` la de lo que se menciona (aquí, los filtros). Una ruta nueva que no
esté aquí hace fallar test_todas_las_rutas_estan_en_el_barrido.
"""

from datetime import timedelta

import pytest
from aislamiento import Barrido, comprobar_cobertura

from app.main import app

RUTAS = {
    # Filtrar por un usuario o un paciente de otra clínica (por id o por texto) no debe revelar sus registros.
    "GET /bitacora": lambda w, ref: dict(url="/bitacora", params=dict(usuario_id=ref.admin, paciente=ref.identificacion)),
    "GET /reportes/citas-por-estado": lambda w, ref: dict(
        url="/reportes/citas-por-estado", params=dict(desde=ref.fecha - timedelta(days=30), hasta=ref.fecha)),
}


def test_todas_las_rutas_estan_en_el_barrido():
    comprobar_cobertura(app, RUTAS)


@pytest.mark.parametrize("ruta", RUTAS)
def test_ninguna_ruta_deja_ver_ni_tocar_otra_clinica_I5(cliente, con, ruta):
    Barrido(cliente, con, ruta, RUTAS[ruta]).correr()
