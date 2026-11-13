"""Unitarias de las reglas de la reserva (RF9, I3, I4, I5): qué valida `validar_y_calcular_fin`, en qué orden bloquea y qué inserta.

Sin base de datos: la conexión es un doble. Que dos reservas simultáneas del mismo espacio terminen en un solo 201 lo decide
el motor, y se prueba en test_concurrencia.py.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from dobles import (FalsaConexion, FalsoRedis, INICIO, OK_ESPACIO, OK_SERVICIO, conexion_de_reserva, confirmar, pedido,
                    sesion_de)
from fastapi import HTTPException

from app import cache
from app.citas import reservar
from app.esquemas import SolicitudReserva
from app.reserva import NO_EXISTEN, validar_y_calcular_fin


def validar(con, *, duracion=None):
    return validar_y_calcular_fin(con, uuid4(), uuid4(), uuid4(), uuid4(), INICIO, duracion=duracion)


# ---------- El fin de la cita (I4) ----------

def test_el_fin_lo_pone_la_duracion_del_servicio():
    assert validar(conexion_de_reserva()) == INICIO + timedelta(minutes=30)


def test_al_reprogramar_manda_la_duracion_que_ya_tenia_la_cita():
    assert validar(conexion_de_reserva(), duracion=timedelta(minutes=45)) == INICIO + timedelta(minutes=45)


# ---------- Bloqueos y clínica (I3, I5) ----------

def test_toma_los_bloqueos_en_orden_y_antes_de_leer_el_horario():
    """Profesional primero, paciente después, y solo entonces el horario y los bloqueos de agenda: así quien los cambia a la
    vez o espera, o ya está confirmado cuando se lee (I3); y el orden fijo evita deadlocks."""
    con = conexion_de_reserva()
    validar(con)
    profesional = con.posicion("FROM profesional WHERE id", "FOR NO KEY UPDATE")
    paciente = con.posicion("FROM paciente WHERE id", "FOR NO KEY UPDATE")
    assert profesional < paciente < con.posicion("AS futuro")


def test_todo_se_busca_con_la_clinica_de_la_sesion_I5():
    clinica, paciente, profesional, servicio = uuid4(), uuid4(), uuid4(), uuid4()
    con = conexion_de_reserva()
    validar_y_calcular_fin(con, clinica, paciente, profesional, servicio, INICIO)
    assert con.parametros("FROM profesional WHERE id") == (profesional, clinica)
    assert con.parametros("FROM paciente WHERE id") == (paciente, clinica)
    assert con.parametros("FROM servicio s LEFT JOIN") == {"clinica": clinica, "profesional": profesional, "servicio": servicio}


# ---------- Lo que se rechaza ----------

@pytest.mark.parametrize("ausente", ["profesional", "paciente", "servicio"])
def test_lo_que_no_existe_en_la_clinica_responde_422_sin_decir_cual(ausente):
    """Un id de otra clínica y uno inexistente dan la misma respuesta: no se revela que existe (I5)."""
    con = conexion_de_reserva(**{ausente: []})
    with pytest.raises(HTTPException) as e:
        validar(con)
    assert (e.value.status_code, e.value.detail) == (422, NO_EXISTEN)
    assert not con.ejecuto("AS futuro")


@pytest.mark.parametrize("cambios, mensaje", [
    ({"servicio": [{**OK_SERVICIO[0], "servicio_activo": False}]}, "El servicio está desactivado"),
    ({"profesional": [{"activo": False}]}, "El profesional no está activo"),
    ({"servicio": [{**OK_SERVICIO[0], "habilitado": False}]}, "El profesional no atiende ese servicio"),
    ({"servicio": [{**OK_SERVICIO[0], "habilitado": None}]}, "El profesional no atiende ese servicio"),    # sin fila en profesional_servicio
    ({"espacio": [{**OK_ESPACIO[0], "futuro": False}]}, "No se puede reservar en el pasado"),
    ({"espacio": [{**OK_ESPACIO[0], "en_horario": False}]}, "Ese horario está fuera de la atención del profesional"),
    ({"espacio": [{**OK_ESPACIO[0], "bloqueado": True}]}, "El profesional tiene un bloqueo de agenda en ese horario"),
])
def test_cada_regla_rechaza_con_su_mensaje(cambios, mensaje):
    with pytest.raises(HTTPException) as e:
        validar(conexion_de_reserva(**cambios))
    assert (e.value.status_code, e.value.detail) == (422, mensaje)


# ---------- La ruta de reservar (RF9) ----------

def solicitud():
    return SolicitudReserva(paciente_id=uuid4(), profesional_id=uuid4(), servicio_id=uuid4(), inicio=INICIO)


def conexion_de_reservar(**cambios):
    return conexion_de_reserva(("INSERT INTO cita", [{"id": uuid4()}]), ("FROM cita c JOIN paciente pa", [{"id": uuid4()}]), **cambios)


def test_la_reserva_inserta_con_la_clinica_y_el_usuario_de_la_sesion_y_el_fin_calculado():
    """Nada de esto viene de la solicitud: ni la clínica (I5), ni quién la crea, ni el fin (I4)."""
    sesion, pedida = sesion_de(), solicitud()
    con = conexion_de_reservar()
    reservar(pedida, pedido(), sesion, con)
    assert con.parametros("INSERT INTO cita") == (
        sesion.clinica_id, pedida.paciente_id, pedida.profesional_id, pedida.servicio_id,
        INICIO, INICIO + timedelta(minutes=30), sesion.usuario_id, None)


def test_una_reserva_rechazada_no_inserta_nada():
    con = conexion_de_reservar(espacio=[{**OK_ESPACIO[0], "bloqueado": True}])
    with pytest.raises(HTTPException):
        reservar(solicitud(), pedido(), sesion_de(), con)
    assert not con.ejecuto("INSERT")


def test_reservar_invalida_la_agenda_del_profesional_despues_del_commit(monkeypatch):
    redis = FalsoRedis()
    monkeypatch.setattr(cache, "_redis", lambda: redis)
    pedida, request = solicitud(), pedido()
    reservar(pedida, request, sesion_de(), conexion_de_reservar())
    assert redis.datos == {}                        # todavía no hubo COMMIT
    confirmar(request)
    assert redis.datos == {f"disp:version:{pedida.profesional_id}": "1"}
