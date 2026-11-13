"""Unitarias de lo que la API acepta (esquemas de pydantic) y de cuándo una cita estorba a un bloqueo.

Son las reglas que se aplican antes de tocar la base: una entrada mal formada se rechaza con 422 sin llegar a ninguna
consulta. Cómo responde la API completa a esas entradas se prueba en test_reserva.py y compañía.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from dobles import INICIO
from pydantic import ValidationError

from app.conflictos import en_bloqueo
from app.esquemas import Cancelacion, Desenlace, NuevoBloqueo, NuevoHorario, SolicitudReserva

UTC = timezone.utc


# ---------- Horarios (RF5) ----------

@pytest.mark.parametrize("hora", ["00:00", "08:00", "13:45", "23:58"])
def test_horas_validas(hora):
    assert NuevoHorario(dia_semana=1, hora_inicio=hora, hora_fin="23:59").hora_inicio == hora


@pytest.mark.parametrize("hora", ["8:00", "24:00", "08:60", "08:00:30", "0800", "", "ocho"])
def test_horas_con_formato_invalido(hora):
    with pytest.raises(ValidationError):
        NuevoHorario(dia_semana=1, hora_inicio=hora, hora_fin="23:59")


@pytest.mark.parametrize("inicio, fin", [("12:00", "12:00"), ("12:00", "08:00")])
def test_el_fin_del_bloque_debe_ser_posterior_al_inicio(inicio, fin):
    with pytest.raises(ValidationError, match="posterior"):
        NuevoHorario(dia_semana=1, hora_inicio=inicio, hora_fin=fin)


@pytest.mark.parametrize("dia", [0, 8, -1])
def test_el_dia_de_la_semana_va_de_1_a_7(dia):
    with pytest.raises(ValidationError):
        NuevoHorario(dia_semana=dia, hora_inicio="08:00", hora_fin="12:00")


# ---------- Bloqueos (RF6) ----------

def test_un_bloqueo_sin_zona_horaria_es_ambiguo_y_se_rechaza():
    with pytest.raises(ValidationError):
        NuevoBloqueo(inicio=datetime(2030, 1, 7, 8), fin=datetime(2030, 1, 8, 8), motivo="Vacaciones")


def test_el_bloqueo_termina_despues_de_empezar():
    with pytest.raises(ValidationError, match="posterior"):
        NuevoBloqueo(inicio=INICIO, fin=INICIO, motivo="Vacaciones")


@pytest.mark.parametrize("motivo, valido", [("  Vacaciones  ", True), ("abc", True), ("ab", False), ("   ", False), ("x" * 200, True), ("x" * 201, False)])
def test_el_motivo_se_recorta_y_tiene_largo_minimo_y_maximo(motivo, valido):
    if valido:
        assert NuevoBloqueo(inicio=INICIO, fin=INICIO + timedelta(days=1), motivo=motivo).motivo == motivo.strip()
    else:
        with pytest.raises(ValidationError):
            NuevoBloqueo(inicio=INICIO, fin=INICIO + timedelta(days=1), motivo=motivo)


# ---------- Reservar (RF9) ----------

def reserva(**cambios):
    return SolicitudReserva(**{"paciente_id": uuid4(), "profesional_id": uuid4(), "servicio_id": uuid4(), "inicio": INICIO, **cambios})


def test_una_reserva_en_regla():
    assert reserva().inicio == INICIO


@pytest.mark.parametrize("campo", ["fin", "clinica_id", "estado"])
def test_lo_que_decide_el_servidor_no_se_acepta_del_cliente_I4_I5(campo):
    """Enviar `fin` o `clinica_id` es un error, no un dato que se ignora en silencio."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        reserva(**{campo: "x"})


def test_el_inicio_debe_tener_zona_y_ser_en_minutos_exactos():
    with pytest.raises(ValidationError):
        reserva(inicio=datetime(2030, 1, 7, 9, 0))                      # sin zona horaria
    with pytest.raises(ValidationError, match="minutos exactos"):
        reserva(inicio=INICIO.replace(second=30))
    with pytest.raises(ValidationError, match="minutos exactos"):
        reserva(inicio=INICIO.replace(microsecond=1))


def test_una_reserva_acepta_cualquier_minuto_exacto_y_no_solo_los_cuartos_de_hora():
    """La disponibilidad ofrece un inicio cada 15 minutos, pero reservar acepta cualquier minuto que cumpla las reglas."""
    assert reserva(inicio=INICIO.replace(minute=7)).inicio.minute == 7


def test_los_ids_deben_ser_uuid():
    with pytest.raises(ValidationError):
        reserva(paciente_id="no-es-un-uuid")


# ---------- Cancelar y desenlace (RF11, RF12) ----------

def test_cancelar_exige_un_motivo_de_al_menos_3_letras():
    assert Cancelacion(motivo=" Aviso ").motivo == "Aviso"
    with pytest.raises(ValidationError):
        Cancelacion(motivo="ab")
    with pytest.raises(ValidationError):
        Cancelacion()


@pytest.mark.parametrize("valor, valido", [("ATENDIDA", True), ("AUSENTE", True), ("CANCELADA", False), ("RESERVADA", False), ("atendida", False)])
def test_el_desenlace_solo_puede_ser_atendida_o_ausente(valor, valido):
    if valido:
        assert Desenlace(desenlace=valor).desenlace == valor
    else:
        with pytest.raises(ValidationError):
            Desenlace(desenlace=valor)


# ---------- Qué citas estorba un bloqueo ----------

def cita(inicio_h, fin_h):
    return {"inicio": datetime(2030, 1, 7, inicio_h, tzinfo=UTC), "fin": datetime(2030, 1, 7, fin_h, tzinfo=UTC)}


BLOQUEO = (datetime(2030, 1, 7, 10, tzinfo=UTC), datetime(2030, 1, 7, 12, tzinfo=UTC))


@pytest.mark.parametrize("cita_, estorba", [
    (cita(8, 10), False),      # termina justo cuando empieza el bloqueo: se tocan, no se solapan
    (cita(12, 14), False),     # empieza justo cuando termina
    (cita(7, 9), False),
    (cita(13, 15), False),
    (cita(10, 12), True),      # coinciden
    (cita(11, 12), True),      # adentro
    (cita(9, 11), True),       # asoma por el principio
    (cita(11, 13), True),      # asoma por el final
    (cita(8, 14), True),       # lo cubre entero
])
def test_una_cita_estorba_si_los_dos_intervalos_se_solapan(cita_, estorba):
    assert (en_bloqueo([cita_], *BLOQUEO) == [cita_]) is estorba


def test_devuelve_solo_las_que_estorban_y_en_su_orden():
    antes, dentro, despues = cita(7, 9), cita(11, 12), cita(14, 15)
    assert en_bloqueo([antes, dentro, despues], *BLOQUEO) == [dentro]
