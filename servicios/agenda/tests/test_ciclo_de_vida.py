"""RF10 a RF13: reprogramar, cancelar, registrar el desenlace y la máquina de estados."""

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from conftest import como, poner_horario, proximo

from app.citas import TRANSICIONES, exigir_transicion

ESTADOS = ["RESERVADA", "ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA"]
FINALES = ESTADOS[1:]


def con_horario(con, mundo, prof=None):
    poner_horario(con, mundo, prof or mundo.prof, 1, "08:00", "12:00")
    poner_horario(con, mundo, prof or mundo.prof, 1, "13:00", "17:00")


def reservada(con, mundo, hora=9, minuto=0, **extra):
    con_horario(con, mundo)
    return mundo.cita(proximo(1, hora, minuto), **extra)


def reprogramar(cliente, quien, cita, inicio, profesional):
    return cliente.post(f"/citas/{cita}/reprogramar", headers=como(quien),
                        json={"profesional_id": str(profesional), "inicio": inicio.isoformat()})


def cancelar(cliente, quien, cita, motivo="El paciente avisó"):
    return cliente.post(f"/citas/{cita}/cancelar", headers=como(quien), json={"motivo": motivo})


def desenlace(cliente, quien, cita, valor="ATENDIDA"):
    return cliente.post(f"/citas/{cita}/desenlace", headers=como(quien), json={"desenlace": valor})


def estado(con, cita):
    return con.execute("SELECT estado FROM cita WHERE id = %s", (cita,)).fetchone()["estado"]


def libres(cliente, mundo):
    r = cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.recepcion),
                    params={"servicio_id": str(mundo.servicio), "fecha": proximo(1, 0).date().isoformat()})
    return [datetime.fromisoformat(e) for e in r.json()["espacios"]]


# ---------- Máquina de estados (RF13): lógica pura ----------

def test_la_tabla_de_transiciones_es_la_del_enunciado():
    assert TRANSICIONES["RESERVADA"] == set(FINALES)
    assert all(TRANSICIONES[e] == set() for e in FINALES)


@pytest.mark.parametrize("de", ESTADOS)
@pytest.mark.parametrize("a", ESTADOS)
def test_cada_par_de_estados(de, a):
    if de == "RESERVADA" and a != "RESERVADA":
        exigir_transicion(de, a)
    else:
        with pytest.raises(Exception) as e:
            exigir_transicion(de, a)
        assert e.value.status_code == 409


# ---------- Reprogramar (RF10) ----------

def test_reprogramar_crea_una_cita_nueva_y_marca_la_antigua(cliente, mundo, con):
    vieja = reservada(con, mundo)
    r = reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 14), mundo.prof)
    assert r.status_code == 201, r.text
    nueva = r.json()
    assert nueva["id"] != str(vieja) and nueva["cita_origen_id"] == str(vieja)
    assert nueva["estado"] == "RESERVADA" and nueva["creada_por"] == str(mundo.recepcion)
    assert nueva["paciente_id"] == str(mundo.paciente) and nueva["servicio_id"] == str(mundo.servicio)
    assert estado(con, vieja) == "REPROGRAMADA"


def test_reprogramar_libera_el_espacio_viejo_y_ocupa_el_nuevo_I7(cliente, mundo, con):
    vieja = reservada(con, mundo)
    assert proximo(1, 9) not in libres(cliente, mundo)
    reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 14), mundo.prof)
    espacios = libres(cliente, mundo)
    assert proximo(1, 9) in espacios and proximo(1, 14) not in espacios


def test_moverla_15_minutos_no_choca_consigo_misma(cliente, mundo, con):
    vieja = reservada(con, mundo)                                  # 09:00-09:30
    assert reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 9, 15), mundo.prof).status_code == 201


def test_reprogramar_a_otro_profesional(cliente, mundo, con):
    vieja = reservada(con, mundo)
    con_horario(con, mundo, mundo.prof2)
    r = reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 9), mundo.prof2)
    assert r.status_code == 201 and r.json()["profesional_id"] == str(mundo.prof2)


def test_si_el_espacio_esta_tomado_la_cita_original_queda_intacta(cliente, mundo, con):
    vieja = reservada(con, mundo)
    otro = mundo.nuevo_paciente()
    con.execute("INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (mundo.clinica_a, otro, mundo.prof, mundo.servicio, proximo(1, 14), proximo(1, 14, 30), mundo.admin))
    r = reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 14), mundo.prof)
    assert r.status_code == 409 and r.json()["restriccion"] == "cita_sin_solape_profesional"
    assert estado(con, vieja) == "RESERVADA"                       # el UPDATE se deshizo con el resto
    assert con.execute("SELECT count(*) AS n FROM cita WHERE cita_origen_id = %s", (vieja,)).fetchone()["n"] == 0


def test_reprogramar_respeta_horario_y_bloqueos_I3(cliente, mundo, con):
    vieja = reservada(con, mundo)
    con.execute("INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo) VALUES (%s,%s,%s,%s,'Permiso')",
                (mundo.clinica_a, mundo.prof, proximo(1, 14), proximo(1, 15)))
    assert "fuera de la atención" in reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 12, 15), mundo.prof).json()["detalle"]
    assert "bloqueo" in reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 14), mundo.prof).json()["detalle"]
    assert estado(con, vieja) == "RESERVADA"


def test_la_duracion_se_conserva_aunque_el_servicio_haya_cambiado_I4(cliente, mundo, con):
    vieja = reservada(con, mundo)                                  # 30 minutos
    con.execute("UPDATE servicio SET duracion_minutos = 60 WHERE id = %s", (mundo.servicio,))
    c = reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 14), mundo.prof).json()
    assert datetime.fromisoformat(c["fin"]) - datetime.fromisoformat(c["inicio"]) == timedelta(minutes=30)


def test_reprogramar_al_mismo_espacio_no_tiene_sentido(cliente, mundo, con):
    vieja = reservada(con, mundo)
    r = reprogramar(cliente, mundo.recepcion, vieja, proximo(1, 9), mundo.prof)
    assert r.status_code == 422 and estado(con, vieja) == "RESERVADA"


def test_reprogramar_una_cadena_de_veces(cliente, mundo, con):
    primera = reservada(con, mundo)
    segunda = reprogramar(cliente, mundo.recepcion, primera, proximo(1, 10), mundo.prof).json()["id"]
    tercera = reprogramar(cliente, mundo.recepcion, segunda, proximo(1, 11), mundo.prof).json()
    assert tercera["cita_origen_id"] == segunda
    r = reprogramar(cliente, mundo.recepcion, primera, proximo(1, 14), mundo.prof)    # la primera ya no es vigente
    assert r.status_code == 409


def test_no_se_puede_enviar_paciente_ni_servicio_al_reprogramar(cliente, mundo, con):
    vieja = reservada(con, mundo)
    r = cliente.post(f"/citas/{vieja}/reprogramar", headers=como(mundo.recepcion),
                     json={"profesional_id": str(mundo.prof), "inicio": proximo(1, 14).isoformat(), "paciente_id": str(mundo.paciente)})
    assert r.status_code == 422


# ---------- Cancelar (RF11) ----------

def test_cancelar_deja_motivo_y_responsable_y_libera_el_espacio_I7(cliente, mundo, con):
    cita = reservada(con, mundo)
    r = cancelar(cliente, mundo.recepcion, cita, "  El paciente avisó  ")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["estado"] == "CANCELADA" and c["cancelada_por"] == str(mundo.recepcion)
    assert c["motivo_cancelacion"] == "El paciente avisó" and c["cancelada_en"]
    assert proximo(1, 9) in libres(cliente, mundo)


def test_cancelar_exige_motivo(cliente, mundo, con):
    cita = reservada(con, mundo)
    for motivo in ("", "  ", "ab", "x" * 201):
        assert cancelar(cliente, mundo.recepcion, cita, motivo).status_code == 422, motivo
    assert estado(con, cita) == "RESERVADA"


# ---------- Desenlace (RF12) ----------

@pytest.mark.parametrize("valor", ["ATENDIDA", "AUSENTE"])
def test_desenlace_de_una_cita_ya_empezada(cliente, mundo, con, valor):
    cita = mundo.cita(datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5))
    r = desenlace(cliente, mundo.recepcion, cita, valor)
    assert r.status_code == 200 and r.json()["estado"] == valor


def test_el_desenlace_no_se_registra_antes_de_la_hora_RF12(cliente, mundo, con):
    cita = reservada(con, mundo)
    r = desenlace(cliente, mundo.recepcion, cita)
    assert r.status_code == 422 and "pasada la hora" in r.json()["detalle"]
    assert estado(con, cita) == "RESERVADA"


def test_el_desenlace_solo_admite_atendida_o_ausente(cliente, mundo, con):
    cita = mundo.cita(datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5))
    for valor in ("CANCELADA", "REPROGRAMADA", "RESERVADA", "otra"):
        assert desenlace(cliente, mundo.recepcion, cita, valor).status_code == 422, valor


def test_atendida_y_ausente_siguen_ocupando_el_espacio(cliente, mundo, con):
    inicio = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    cita = mundo.cita(inicio)
    desenlace(cliente, mundo.recepcion, cita, "AUSENTE")
    with pytest.raises(psycopg.errors.ExclusionViolation), con.transaction():
        mundo.cita(inicio, profesional=mundo.prof)


# ---------- Transiciones por la API (RF13) ----------

@pytest.mark.parametrize("final", FINALES)
def test_un_estado_final_no_admite_ninguna_operacion(cliente, mundo, con, final):
    # Las finales se crean ya en ese estado, en el pasado cercano para que el desenlace pase la regla de la hora.
    cita = mundo.cita(datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5), estado=final)
    con_horario(con, mundo)
    assert cancelar(cliente, mundo.recepcion, cita).status_code == 409
    assert desenlace(cliente, mundo.recepcion, cita, "ATENDIDA").status_code == 409
    assert desenlace(cliente, mundo.recepcion, cita, "AUSENTE").status_code == 409
    assert reprogramar(cliente, mundo.recepcion, cita, proximo(1, 14), mundo.prof).status_code == 409
    assert estado(con, cita) == final


def test_el_mensaje_dice_que_transicion_se_rechazo(cliente, mundo, con):
    cita = reservada(con, mundo)
    cancelar(cliente, mundo.recepcion, cita)
    assert cancelar(cliente, mundo.recepcion, cita).json()["detalle"] == "Una cita cancelada no puede pasar a cancelada"


# ---------- Segunda barrera en el motor (migración 007) ----------

def test_el_motor_tambien_rechaza_una_transicion_que_salte_la_api(mundo, con):
    cita = mundo.cita(proximo(1, 9), estado="CANCELADA")
    with pytest.raises(psycopg.errors.CheckViolation) as e, con.transaction():
        con.execute("UPDATE cita SET motivo_cancelacion = 'otro' WHERE id = %s", (cita,))
    assert e.value.diag.constraint_name == "cita_transicion_permitida"


def test_el_motor_rechaza_editar_la_duracion_I4(mundo, con):
    cita = mundo.cita(proximo(1, 9))
    with pytest.raises(psycopg.errors.CheckViolation) as e, con.transaction():
        con.execute("UPDATE cita SET fin = fin + interval '1 hour' WHERE id = %s", (cita,))
    assert e.value.diag.constraint_name == "cita_datos_inmutables"


# ---------- Permisos y aislamiento ----------

def test_permisos_de_reprogramar_y_cancelar(cliente, mundo, con):
    cita = reservada(con, mundo)
    for quien in (mundo.usuario_prof, mundo.plataforma):
        assert cancelar(cliente, quien, cita).status_code == 403
        assert reprogramar(cliente, quien, cita, proximo(1, 14), mundo.prof).status_code == 403
    assert cliente.post(f"/citas/{cita}/cancelar", json={"motivo": "sin sesión"}).status_code == 401
    assert cancelar(cliente, mundo.admin, cita).status_code == 200


def test_permisos_del_desenlace(cliente, mundo, con):
    """La matriz dice "sí" para el profesional, sin el "solo los propios" de otras filas, y no se puede reducir."""
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    assert desenlace(cliente, mundo.plataforma, mundo.cita(ahora - timedelta(hours=9))).status_code == 403
    for i, quien in enumerate((mundo.admin, mundo.recepcion, mundo.usuario_prof, mundo.usuario_prof2)):
        cita = mundo.cita(ahora - timedelta(hours=i + 1))
        assert desenlace(cliente, quien, cita).status_code == 200


def test_otra_clinica_no_alcanza_la_cita_I5(cliente, mundo, con):
    cita = reservada(con, mundo)
    afuera = mundo.admin_otra_clinica
    assert cancelar(cliente, afuera, cita).status_code == 404
    assert desenlace(cliente, afuera, cita).status_code == 404
    assert reprogramar(cliente, afuera, cita, proximo(1, 14), mundo.prof).status_code == 404
    assert estado(con, cita) == "RESERVADA"


def test_cita_inexistente_y_id_mal_formado(cliente, mundo):
    assert cancelar(cliente, mundo.recepcion, uuid.uuid4()).status_code == 404
    assert cancelar(cliente, mundo.recepcion, "no-es-uuid").status_code == 422
