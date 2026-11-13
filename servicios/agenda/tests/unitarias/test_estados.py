"""Unitarias de los estados de la cita (RF10 a RF13): la máquina de estados y lo que cada operación decide por su cuenta.

Sin base de datos. Que el motor también rechace una transición (trigger de la migración 007) se prueba en test_ciclo_de_vida.py.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from dobles import FalsaConexion, FalsoRedis, INICIO, conexion_de_reserva, confirmar, fila_de_cita, pedido, sesion_de
from fastapi import HTTPException

from app import cache
from app.citas import TRANSICIONES, cancelar, exigir_transicion, registrar_desenlace, reprogramar
from app.esquemas import Cancelacion, Desenlace, Reprogramacion

ESTADOS = ["RESERVADA", "ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA"]
FINALES = ESTADOS[1:]
VISTA = ("FROM cita c JOIN paciente pa", [{"id": uuid4()}])      # la lectura que arma la respuesta; su contenido da igual


@pytest.fixture
def redis(monkeypatch):
    falso = FalsoRedis()
    monkeypatch.setattr(cache, "_redis", lambda: falso)
    return falso


# ---------- La máquina de estados (RF13) ----------

def test_la_tabla_de_transiciones_es_la_del_enunciado():
    assert TRANSICIONES["RESERVADA"] == set(FINALES)
    assert all(TRANSICIONES[e] == set() for e in FINALES)


@pytest.mark.parametrize("de", ESTADOS)
@pytest.mark.parametrize("a", ESTADOS)
def test_cada_par_de_estados(de, a):
    if de == "RESERVADA" and a != "RESERVADA":
        exigir_transicion(de, a)
    else:
        with pytest.raises(HTTPException) as e:
            exigir_transicion(de, a)
        assert e.value.status_code == 409


def test_el_mensaje_nombra_los_dos_estados():
    with pytest.raises(HTTPException) as e:
        exigir_transicion("CANCELADA", "ATENDIDA")
    assert e.value.detail == "Una cita cancelada no puede pasar a atendida"


# ---------- Desenlace (RF12) ----------

def test_el_desenlace_se_registra_si_la_hora_ya_paso():
    cita = fila_de_cita(futura=False)
    con = FalsaConexion(("FROM cita WHERE id", [cita]), ("UPDATE cita SET estado", []), VISTA)
    registrar_desenlace(cita["id"], Desenlace(desenlace="AUSENTE"), sesion_de(), con)
    assert con.parametros("UPDATE cita SET estado") == ("AUSENTE", cita["id"])


def test_el_desenlace_no_se_registra_antes_de_la_hora():
    cita = fila_de_cita(futura=True)
    con = FalsaConexion(("FROM cita WHERE id", [cita]))
    with pytest.raises(HTTPException) as e:
        registrar_desenlace(cita["id"], Desenlace(desenlace="ATENDIDA"), sesion_de(), con)
    assert e.value.status_code == 422 and not con.ejecuto("UPDATE cita SET")


def test_primero_se_revisa_la_transicion_y_despues_la_hora():
    """Una cita cancelada y futura responde 409 (no puede cambiar de estado), no 422 (todavía no es la hora)."""
    cita = fila_de_cita(estado="CANCELADA", futura=True)
    con = FalsaConexion(("FROM cita WHERE id", [cita]))
    with pytest.raises(HTTPException) as e:
        registrar_desenlace(cita["id"], Desenlace(desenlace="ATENDIDA"), sesion_de(), con)
    assert e.value.status_code == 409


def test_la_cita_se_busca_con_la_clinica_de_la_sesion_y_bloqueada_I5():
    sesion, cita_id = sesion_de(), uuid4()
    con = FalsaConexion(("FROM cita WHERE id", []))
    with pytest.raises(HTTPException) as e:
        registrar_desenlace(cita_id, Desenlace(desenlace="ATENDIDA"), sesion, con)
    assert e.value.status_code == 404
    assert con.parametros("FROM cita WHERE id") == (cita_id, sesion.clinica_id)
    assert con.ejecuto("FROM cita WHERE id", "FOR NO KEY UPDATE")


# ---------- Cancelar (RF11) ----------

def test_cancelar_guarda_quien_y_por_que_y_libera_la_agenda_del_profesional(redis):
    sesion, cita, request = sesion_de(), fila_de_cita(), pedido()
    con = FalsaConexion(("FROM cita WHERE id", [cita]), ("UPDATE cita SET estado = 'CANCELADA'", []), VISTA)
    cancelar(cita["id"], Cancelacion(motivo="El paciente avisó"), request, sesion, con)

    assert con.parametros("UPDATE cita SET estado = 'CANCELADA'") == (sesion.usuario_id, "El paciente avisó", cita["id"])
    assert redis.datos == {}                           # nada se invalida antes del COMMIT
    confirmar(request)
    assert redis.datos == {f"disp:version:{cita['profesional_id']}": "1"}


@pytest.mark.parametrize("estado", FINALES)
def test_una_cancelacion_rechazada_no_toca_nada_ni_invalida(redis, estado):
    cita, request = fila_de_cita(estado=estado), pedido()
    con = FalsaConexion(("FROM cita WHERE id", [cita]))
    with pytest.raises(HTTPException) as e:
        cancelar(cita["id"], Cancelacion(motivo="Intento"), request, sesion_de(), con)
    assert e.value.status_code == 409
    assert not con.ejecuto("UPDATE cita SET") and request.state.tras_commit == []


# ---------- Reprogramar (RF10) ----------

def destino_de(cita, **cambios):
    return Reprogramacion(profesional_id=cambios.get("profesional_id", cita["profesional_id"]),
                          inicio=cambios.get("inicio", INICIO + timedelta(hours=2)))


def conexion_de_reprogramacion(cita):
    return conexion_de_reserva(
        ("FROM cita WHERE id", [cita]), ("UPDATE cita SET estado = 'REPROGRAMADA'", []),
        ("INSERT INTO cita", [{"id": uuid4()}]), VISTA)


def test_elegir_el_mismo_espacio_se_rechaza_antes_de_bloquear_nada():
    cita = fila_de_cita()
    con = conexion_de_reprogramacion(cita)
    with pytest.raises(HTTPException) as e:
        reprogramar(cita["id"], destino_de(cita, inicio=cita["inicio"]), pedido(), sesion_de(), con)
    assert e.value.status_code == 422
    assert not con.ejecuto("FOR NO KEY UPDATE") and not con.ejecuto("UPDATE cita SET") and not con.ejecuto("INSERT")


def test_el_espacio_viejo_se_libera_antes_de_ocupar_el_nuevo():
    """Si el INSERT fuera primero, moverla 15 minutos chocaría consigo misma con la exclusión del motor."""
    cita = fila_de_cita()
    con = conexion_de_reprogramacion(cita)
    reprogramar(cita["id"], destino_de(cita), pedido(), sesion_de(), con)
    assert con.posicion("UPDATE cita SET estado = 'REPROGRAMADA'") < con.posicion("INSERT INTO cita")


def test_los_bloqueos_se_toman_en_orden_profesional_paciente_cita():
    """El orden fijo evita que dos operaciones se esperen en círculo (deadlock)."""
    cita = fila_de_cita()
    con = conexion_de_reprogramacion(cita)
    reprogramar(cita["id"], destino_de(cita), pedido(), sesion_de(), con)
    profesional = con.posicion("FROM profesional WHERE id", "FOR NO KEY UPDATE")
    paciente = con.posicion("FROM paciente WHERE id", "FOR NO KEY UPDATE")
    cita_bloqueada = con.posicion("FROM cita WHERE id", "FOR NO KEY UPDATE")
    assert profesional < paciente < cita_bloqueada


def test_la_cita_nueva_conserva_paciente_servicio_y_duracion_I4():
    """La cita dura 45 min aunque el servicio hoy dure 30: reprogramar no la altera."""
    sesion, cita = sesion_de(), fila_de_cita(minutos=45)
    destino = destino_de(cita, profesional_id=uuid4())
    con = conexion_de_reprogramacion(cita)
    reprogramar(cita["id"], destino, pedido(), sesion, con)
    assert con.parametros("INSERT INTO cita") == (
        sesion.clinica_id, cita["paciente_id"], destino.profesional_id, cita["servicio_id"],
        destino.inicio, destino.inicio + timedelta(minutes=45), sesion.usuario_id, cita["id"])


def test_reprogramar_a_otro_profesional_libera_las_dos_agendas(redis):
    cita, request = fila_de_cita(), pedido()
    destino = destino_de(cita, profesional_id=uuid4())
    reprogramar(cita["id"], destino, request, sesion_de(), conexion_de_reprogramacion(cita))
    confirmar(request)
    assert redis.datos == {f"disp:version:{cita['profesional_id']}": "1", f"disp:version:{destino.profesional_id}": "1"}


def test_reprogramar_con_el_mismo_profesional_invalida_su_agenda_una_sola_vez(redis):
    cita, request = fila_de_cita(), pedido()
    reprogramar(cita["id"], destino_de(cita), request, sesion_de(), conexion_de_reprogramacion(cita))
    confirmar(request)
    assert redis.datos == {f"disp:version:{cita['profesional_id']}": "1"}


def test_una_reprogramacion_rechazada_no_invalida(redis):
    cita, request = fila_de_cita(estado="CANCELADA"), pedido()
    with pytest.raises(HTTPException) as e:
        reprogramar(cita["id"], destino_de(cita), request, sesion_de(), conexion_de_reprogramacion(cita))
    assert e.value.status_code == 409 and request.state.tras_commit == []
