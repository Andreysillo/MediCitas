"""RF19: consulta de la bitácora (solo administrador de clínica; filtros por usuario, paciente y fechas)."""

import uuid
from datetime import datetime

import pytest

from conftest import CR, como


def consultar(cliente, quien, **filtros):
    return cliente.get("/bitacora", params={k: str(v) for k, v in filtros.items()}, headers=como(quien))


@pytest.mark.parametrize("quien", ["recepcion", "profesional_usuario", "plataforma"])
def test_otros_roles_403(cliente, mundo, quien):
    assert consultar(cliente, getattr(mundo, quien)).status_code == 403


def test_sin_sesion_401(cliente):
    assert cliente.get("/bitacora").status_code == 401


def test_devuelve_registros_recientes_primero_con_nombres(cliente, mundo):
    viejo = mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 1, 9, tzinfo=CR))
    nuevo = mundo.registro(mundo.a, mundo.profesional_usuario, mundo.beto, datetime(2026, 3, 2, 9, tzinfo=CR),
                           "ESCRITURA", "NOTA_CLINICA")
    r = consultar(cliente, mundo.admin).json()
    assert r["total"] == 2 and [x["id"] for x in r["registros"]] == [nuevo, viejo]
    primero = r["registros"][0]
    assert (primero["usuario"], primero["rol"], primero["accion"], primero["recurso"]) == ("Dra. Uno", "PROFESIONAL", "ESCRITURA", "NOTA_CLINICA")
    assert (primero["paciente"], primero["identificacion"].startswith("222")) == ("Beto Mora", True)


def test_no_muestra_la_bitacora_de_otra_clinica(cliente, mundo):
    mundo.registro(mundo.b, mundo.admin_b, mundo.ajeno, datetime(2026, 3, 1, 9, tzinfo=CR))
    assert consultar(cliente, mundo.admin).json() == {"total": 0, "registros": []}
    # Pasar datos de la otra clínica como filtro tampoco los revela (I5).
    assert consultar(cliente, mundo.admin, usuario_id=mundo.admin_b, paciente="Ajeno", clinica_id=mundo.b).json()["total"] == 0


def test_filtra_por_usuario(cliente, mundo):
    mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 1, 9, tzinfo=CR))
    mundo.registro(mundo.a, mundo.profesional_usuario, mundo.ana, datetime(2026, 3, 1, 10, tzinfo=CR))
    r = consultar(cliente, mundo.admin, usuario_id=mundo.recepcion).json()
    assert r["total"] == 1 and r["registros"][0]["usuario"] == "Recepción A"
    assert consultar(cliente, mundo.admin, usuario_id=uuid.uuid4()).json()["total"] == 0


def test_filtra_por_paciente_por_nombre_o_identificacion(cliente, mundo):
    mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 1, 9, tzinfo=CR))
    mundo.registro(mundo.a, mundo.recepcion, mundo.beto, datetime(2026, 3, 1, 10, tzinfo=CR))
    assert consultar(cliente, mundo.admin, paciente="solís").json()["total"] == 1
    assert consultar(cliente, mundo.admin, paciente="222").json()["total"] == 1
    assert consultar(cliente, mundo.admin, paciente="%").json()["total"] == 0


def test_rango_de_fechas_usa_el_dia_local_e_incluye_ambos_extremos(cliente, mundo):
    mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 1, 0, 0, tzinfo=CR))    # primer instante del 1
    mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 2, 23, 59, tzinfo=CR))  # último instante del 2
    mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 3, 0, 0, tzinfo=CR))    # ya es el 3
    assert consultar(cliente, mundo.admin, desde="2026-03-01", hasta="2026-03-02").json()["total"] == 2
    assert consultar(cliente, mundo.admin, desde="2026-03-03").json()["total"] == 1
    assert consultar(cliente, mundo.admin, hasta="2026-02-28").json()["total"] == 0


@pytest.mark.parametrize("filtros", [{"desde": "2026-03-05", "hasta": "2026-03-01"}, {"desde": "no-es-fecha"}, {"usuario_id": "x"}])
def test_filtros_invalidos_422(cliente, mundo, filtros):
    assert consultar(cliente, mundo.admin, **filtros).status_code == 422


def test_limita_a_100_pero_informa_el_total(cliente, mundo):
    for i in range(103):
        mundo.registro(mundo.a, mundo.recepcion, mundo.ana, datetime(2026, 3, 1, 9, tzinfo=CR))
    r = consultar(cliente, mundo.admin).json()
    assert r["total"] == 103 and len(r["registros"]) == 100


def test_la_ruta_no_permite_modificar(cliente, mundo):
    for metodo in ("post", "put", "patch", "delete"):
        assert getattr(cliente, metodo)("/bitacora", headers=como(mundo.admin)).status_code == 405
