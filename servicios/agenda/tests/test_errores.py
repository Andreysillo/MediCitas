"""T35: entrada mal formada y recurso inexistente en TODAS las rutas de agenda, sin caída del servicio. Motor: errores.py (servicios/pruebas_comunes).

Las solicitudes son las de test_aislamiento_i5.RUTAS. Una ruta nueva sin fila allí hace fallar test_todas_las_rutas_estan_en_el_barrido.
Las unitarias de cómo se traduce cada error están en tests/unitarias/test_manejo_de_errores.py.
"""

import pytest
from errores import Errores
from test_aislamiento_i5 import RUTAS


@pytest.mark.parametrize("ruta", RUTAS)
def test_una_entrada_mal_formada_o_un_recurso_inexistente_nunca_tumban_el_servicio_RO3(cliente, con, ruta):
    Errores(cliente, con, ruta, RUTAS[ruta]).correr()
