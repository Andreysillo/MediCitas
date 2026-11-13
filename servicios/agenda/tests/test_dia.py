"""RF20: agenda del día, de un profesional o de toda la clínica."""

import uuid
from datetime import datetime

import pytest

from conftest import CR, como

DIA = "2026-03-10"


def agenda(cliente, quien, **params):
    return cliente.get("/agenda", params={"fecha": DIA, **{k: str(v) for k, v in params.items()}}, headers=como(quien))


def hora(h, m=0):
    return datetime(2026, 3, 10, h, m, tzinfo=CR)


def test_sin_sesion_401_y_plataforma_403(cliente, mundo):
    assert cliente.get("/agenda", params={"fecha": DIA}).status_code == 401
    assert agenda(cliente, mundo.plataforma).status_code == 403


def test_clinica_completa_ordenada_por_hora(cliente, mundo):
    tarde = mundo.cita(hora(15))
    manana = mundo.cita(hora(8), profesional=mundo.prof2)
    r = agenda(cliente, mundo.recepcion).json()
    assert [c["id"] for c in r] == [str(manana), str(tarde)]
    assert (r[0]["profesional"], r[0]["paciente"], r[0]["servicio"], r[0]["estado"]) == ("Dr. Dos", "Paciente Uno", "Consulta", "RESERVADA")


def test_filtra_por_profesional(cliente, mundo):
    mundo.cita(hora(8), profesional=mundo.prof2)
    propia = mundo.cita(hora(9))
    r = agenda(cliente, mundo.admin, profesional_id=mundo.prof).json()
    assert [c["id"] for c in r] == [str(propia)]


def test_solo_el_dia_local_de_la_clinica(cliente, mundo):
    dentro = [mundo.cita(hora(0)), mundo.cita(hora(23, 30))]
    mundo.cita(datetime(2026, 3, 11, 0, tzinfo=CR))
    mundo.cita(datetime(2026, 3, 9, 23, 30, tzinfo=CR))
    assert [c["id"] for c in agenda(cliente, mundo.admin).json()] == [str(x) for x in dentro]


def test_reprogramadas_no_salen_pero_canceladas_si(cliente, mundo):
    mundo.cita(hora(8), "REPROGRAMADA")
    cancelada = mundo.cita(hora(9), "CANCELADA")
    r = agenda(cliente, mundo.admin).json()
    assert [(c["id"], c["estado"]) for c in r] == [(str(cancelada), "CANCELADA")]


def test_el_profesional_solo_ve_la_suya(cliente, mundo):
    propia = mundo.cita(hora(8))
    mundo.cita(hora(9), profesional=mundo.prof2)
    assert [c["id"] for c in agenda(cliente, mundo.usuario_prof).json()] == [str(propia)]
    assert [c["id"] for c in agenda(cliente, mundo.usuario_prof, profesional_id=mundo.prof).json()] == [str(propia)]
    assert agenda(cliente, mundo.usuario_prof, profesional_id=mundo.prof2).status_code == 404


def test_otra_clinica_no_ve_nada_y_su_profesional_da_404(cliente, mundo):
    mundo.cita(hora(8))
    assert agenda(cliente, mundo.admin_otra_clinica).json() == []
    assert agenda(cliente, mundo.admin_otra_clinica, profesional_id=mundo.prof).status_code == 404
    assert agenda(cliente, mundo.admin, profesional_id=uuid.uuid4()).status_code == 404


@pytest.mark.parametrize("fecha", ["no-es-fecha", "2026-02-31"])
def test_fecha_invalida_422(cliente, mundo, fecha):
    assert cliente.get("/agenda", params={"fecha": fecha}, headers=como(mundo.admin)).status_code == 422
