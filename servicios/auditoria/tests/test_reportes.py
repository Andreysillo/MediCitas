"""RF21: citas por estado en un rango de fechas."""

from datetime import datetime, timedelta

import pytest

from conftest import CR, como

ESTADOS = ["RESERVADA", "ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA"]


def reporte(cliente, quien, desde, hasta):
    return cliente.get("/reportes/citas-por-estado", params={"desde": desde, "hasta": hasta}, headers=como(quien))


@pytest.mark.parametrize("quien", ["recepcion", "profesional_usuario", "plataforma"])
def test_otros_roles_403(cliente, mundo, quien):
    assert reporte(cliente, getattr(mundo, quien), "2026-03-01", "2026-03-31").status_code == 403


def test_sin_sesion_401(cliente):
    assert cliente.get("/reportes/citas-por-estado", params={"desde": "2026-03-01", "hasta": "2026-03-31"}).status_code == 401


def test_cuenta_por_estado_y_trae_todos_los_estados(cliente, mundo):
    dia = datetime(2026, 3, 10, 8, tzinfo=CR)
    pacientes = [mundo.ana, mundo.beto]
    # Un profesional no puede tener dos citas vigentes solapadas (I1): cada cita va a una hora distinta.
    mundo.cita(dia, "ATENDIDA")
    mundo.cita(dia + timedelta(hours=1), "ATENDIDA", pacientes[1])
    mundo.cita(dia + timedelta(hours=2), "AUSENTE")
    mundo.cita(dia + timedelta(hours=3), "CANCELADA")
    r = reporte(cliente, mundo.admin, "2026-03-10", "2026-03-10").json()
    assert r["total"] == 4
    assert r["por_estado"] == {"RESERVADA": 0, "ATENDIDA": 2, "AUSENTE": 1, "CANCELADA": 1, "REPROGRAMADA": 0}
    assert list(r["por_estado"]) == ESTADOS


def test_los_extremos_del_rango_se_miden_en_dia_local(cliente, mundo):
    mundo.cita(datetime(2026, 3, 10, 0, 0, tzinfo=CR), "ATENDIDA")       # primer instante del 10
    mundo.cita(datetime(2026, 3, 10, 23, 30, tzinfo=CR), "ATENDIDA")     # último espacio del 10
    mundo.cita(datetime(2026, 3, 11, 0, 0, tzinfo=CR), "ATENDIDA")       # ya es el 11
    assert reporte(cliente, mundo.admin, "2026-03-10", "2026-03-10").json()["total"] == 2
    assert reporte(cliente, mundo.admin, "2026-03-10", "2026-03-11").json()["total"] == 3


def test_no_cuenta_citas_de_otra_clinica(cliente, con, mundo):
    mundo.cita(datetime(2026, 3, 10, 8, tzinfo=CR), "ATENDIDA")
    assert reporte(cliente, mundo.admin_b, "2026-03-10", "2026-03-10").json()["total"] == 0


@pytest.mark.parametrize("desde,hasta", [("2026-03-10", "2026-03-01"), ("2025-01-01", "2026-03-01"), ("x", "2026-03-01")])
def test_rango_invalido_422(cliente, mundo, desde, hasta):
    assert reporte(cliente, mundo.admin, desde, hasta).status_code == 422


def test_rango_de_un_ano_completo_se_acepta(cliente, mundo):
    assert reporte(cliente, mundo.admin, "2026-01-01", "2026-12-31").status_code == 200
