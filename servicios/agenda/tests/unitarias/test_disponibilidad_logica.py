"""Unitarias de la disponibilidad (RF7, RF8): lo que las rutas deciden alrededor de la consulta SQL.

El cálculo de los espacios vive en UNA consulta SQL (app/espacios.py), así que sus resultados (qué horas salen libres) solo se
pueden probar con la base real: ver test_disponibilidad.py. Aquí se prueba el resto, sin base ni Redis: qué se valida y en qué
orden, cuándo se usa la caché, cómo se arman los parámetros y cómo se agrupa la respuesta de RF8.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from dobles import FalsaConexion, sesion_de
from fastapi import HTTPException

from app import cache, disponibilidad
from app.disponibilidad import disponibilidad_de_profesional, disponibilidad_de_servicio
from app.espacios import _SQL, PASO_MINUTOS, espacios_libres

FECHA = date(2030, 1, 7)
ZONA = "America/Costa_Rica"
SERVICIO = ("FROM servicio s JOIN clinica c", [{"duracion_minutos": 30, "zona_horaria": ZONA}])
ATIENDE = ("FROM profesional p WHERE p.id", [{"atiende": True}])


def hora(h, m=0, dia=FECHA):
    return datetime(dia.year, dia.month, dia.day, h, m, tzinfo=timezone.utc)


@pytest.fixture
def calculos(monkeypatch):
    """Reemplaza el cálculo en SQL por una lista de llamadas: cada una guarda los argumentos con que se pidió."""
    llamadas = []

    def falso(con, **kwargs):
        llamadas.append(kwargs)
        return [{"profesional_id": kwargs.get("profesional_id"), "fecha": FECHA, "inicio": hora(9)}]

    monkeypatch.setattr(disponibilidad, "espacios_libres", falso)
    return llamadas


@pytest.fixture
def sin_redis(monkeypatch):
    monkeypatch.setattr(cache, "_redis", lambda: None)


# ---------- RF7: validaciones antes de calcular ----------

def test_un_servicio_que_no_es_de_la_clinica_responde_404_y_no_consulta_mas(calculos):
    sesion, servicio_id = sesion_de(), uuid4()
    con = FalsaConexion(("FROM servicio s JOIN clinica c", []))
    with pytest.raises(HTTPException) as e:
        disponibilidad_de_profesional(uuid4(), servicio_id, FECHA, None, sesion, con)
    assert e.value.status_code == 404
    assert con.parametros("FROM servicio s") == (servicio_id, sesion.clinica_id)       # la clínica es la de la sesión (I5)
    assert len(con.sentencias) == 1 and calculos == []


def test_un_profesional_que_no_es_de_la_clinica_responde_404(calculos):
    sesion, servicio_id, profesional_id = sesion_de(), uuid4(), uuid4()
    con = FalsaConexion(SERVICIO, ("FROM profesional p WHERE p.id", []))
    with pytest.raises(HTTPException) as e:
        disponibilidad_de_profesional(profesional_id, servicio_id, FECHA, None, sesion, con)
    assert e.value.status_code == 404
    assert con.parametros("FROM profesional p WHERE p.id") == (servicio_id, profesional_id, sesion.clinica_id)
    assert calculos == []


def test_si_el_profesional_no_atiende_el_servicio_se_avisa_antes_de_calcular(calculos, monkeypatch):
    monkeypatch.setattr(cache, "espacios", lambda *a: pytest.fail("no debía tocar la caché"))
    con = FalsaConexion(SERVICIO, ("FROM profesional p WHERE p.id", [{"atiende": False}]))
    with pytest.raises(HTTPException) as e:
        disponibilidad_de_profesional(uuid4(), uuid4(), FECHA, None, sesion_de(), con)
    assert (e.value.status_code, e.value.detail) == (422, "Ese profesional no atiende ese servicio")
    assert calculos == []


# ---------- RF7: la caché ----------

def test_la_caché_se_consulta_con_la_clave_completa_y_su_respuesta_se_usa_tal_cual(calculos, monkeypatch):
    pedidos = []

    def caché(clinica, profesional, servicio, duracion, fecha, calcular):
        pedidos.append((clinica, profesional, servicio, duracion, fecha))
        return [hora(10)]

    monkeypatch.setattr(cache, "espacios", caché)
    sesion, profesional_id, servicio_id = sesion_de(), uuid4(), uuid4()
    r = disponibilidad_de_profesional(profesional_id, servicio_id, FECHA, None, sesion, FalsaConexion(SERVICIO, ATIENDE))
    assert pedidos == [(sesion.clinica_id, profesional_id, servicio_id, 30, FECHA)]
    assert r["espacios"] == [hora(10)] and r["duracion_minutos"] == 30
    assert calculos == []                              # con copia guardada, la base no calcula


def test_lo_que_calcula_la_caché_cuando_no_hay_copia_es_un_dia_de_ese_profesional(calculos, monkeypatch):
    monkeypatch.setattr(cache, "espacios", lambda *a: a[-1]())          # la caché pide calcular
    sesion, profesional_id, servicio_id = sesion_de(), uuid4(), uuid4()
    r = disponibilidad_de_profesional(profesional_id, servicio_id, FECHA, None, sesion, FalsaConexion(SERVICIO, ATIENDE))
    assert r["espacios"] == [hora(9)]
    (llamada,) = calculos
    assert (llamada["clinica_id"], llamada["servicio_id"], llamada["profesional_id"]) == (sesion.clinica_id, servicio_id, profesional_id)
    assert (llamada["zona_horaria"], llamada["duracion_minutos"], llamada["desde"], llamada["dias"]) == (ZONA, 30, FECHA, 1)
    assert llamada["ignorar_cita"] is None


def test_ignorar_cita_nunca_pasa_por_la_caché(calculos, monkeypatch):
    """Esa respuesta muestra libre un espacio ocupado: guardada, se la daría a todos los demás (I8)."""
    monkeypatch.setattr(cache, "espacios", lambda *a: pytest.fail("ignorar_cita no debe usar la caché"))
    cita = uuid4()
    r = disponibilidad_de_profesional(uuid4(), uuid4(), FECHA, cita, sesion_de(), FalsaConexion(SERVICIO, ATIENDE))
    assert calculos[0]["ignorar_cita"] == cita and r["espacios"] == [hora(9)]


def test_sin_redis_se_calcula_en_la_base(calculos, sin_redis):
    r = disponibilidad_de_profesional(uuid4(), uuid4(), FECHA, None, sesion_de(), FalsaConexion(SERVICIO, ATIENDE))
    assert r["espacios"] == [hora(9)] and len(calculos) == 1


# ---------- RF8 ----------

def test_rf8_sin_espacios_responde_lista_vacia_sin_buscar_profesionales(monkeypatch):
    monkeypatch.setattr(disponibilidad, "espacios_libres", lambda con, **kw: [])
    con = FalsaConexion(SERVICIO)
    assert disponibilidad_de_servicio(uuid4(), FECHA, 7, None, sesion_de(), con) == []
    assert not con.ejecuto("FROM profesional p JOIN usuario")


def test_rf8_agrupa_por_profesional_y_devuelve_todos_los_dias_del_rango(monkeypatch):
    a, b = uuid4(), uuid4()
    filas = [
        {"profesional_id": a, "fecha": FECHA, "inicio": hora(9)},
        {"profesional_id": a, "fecha": FECHA, "inicio": hora(9, 15)},
        {"profesional_id": a, "fecha": FECHA + timedelta(days=2), "inicio": hora(8, dia=FECHA + timedelta(days=2))},
        {"profesional_id": b, "fecha": FECHA + timedelta(days=1), "inicio": hora(10, dia=FECHA + timedelta(days=1))},
    ]
    llamadas = []
    monkeypatch.setattr(disponibilidad, "espacios_libres", lambda con, **kw: llamadas.append(kw) or filas)
    sesion = sesion_de()
    nombres = [{"id": a, "nombre": "Ana", "especialidad": "General"}, {"id": b, "nombre": "Beto", "especialidad": "General"}]
    con = FalsaConexion(SERVICIO, ("FROM profesional p JOIN usuario", nombres))

    r = disponibilidad_de_servicio(uuid4(), FECHA, 3, None, sesion, con)

    assert [p["profesional"]["nombre"] for p in r] == ["Ana", "Beto"]
    dias = [FECHA + timedelta(days=i) for i in range(3)]
    for profesional in r:
        assert [d["fecha"] for d in profesional["dias"]] == dias               # también los días sin espacio
    assert [len(d["espacios"]) for d in r[0]["dias"]] == [2, 0, 1]
    assert [len(d["espacios"]) for d in r[1]["dias"]] == [0, 1, 0]
    assert "profesional_id" not in llamadas[0] and llamadas[0]["dias"] == 3     # todos los de la clínica
    clinica, ids = con.parametros("FROM profesional p JOIN usuario")
    assert clinica == sesion.clinica_id and sorted(ids) == sorted([a, b])


# ---------- espacios.py: cómo se arma la consulta ----------

def test_espacios_libres_arma_los_parametros_y_no_prepara_la_consulta():
    clinica, servicio = uuid4(), uuid4()
    con = FalsaConexion(("WITH dias AS", []))
    espacios_libres(con, clinica_id=clinica, servicio_id=servicio, zona_horaria=ZONA, duracion_minutos=45, desde=FECHA, dias=7)
    sql, params, opciones = con.sentencias[0]
    assert params == {"clinica": clinica, "servicio": servicio, "profesional": None, "ignorar": None, "zona": ZONA,
                      "desde": FECHA, "dias": 7, "duracion": timedelta(minutes=45), "paso": timedelta(minutes=PASO_MINUTOS)}
    # Preparada, Postgres puede pasarse a un plan genérico que lee las tablas enteras (medido en T15: RF7 de 1,2 a 99 ms).
    assert opciones == {"prepare": False}


def test_la_consulta_conserva_las_decisiones_de_rendimiento_de_t15():
    """No hay forma barata de probar el rendimiento en una unitaria, pero sí de avisar si alguien quita lo que lo sostiene."""
    assert "habilitados AS MATERIALIZED" in _SQL                    # descarta primero a quien no atiende el servicio
    assert _SQL.count("%(profesional)s::uuid IS NULL OR") == 3      # …y le dice al planificador qué profesional es (ver espacios.py)
