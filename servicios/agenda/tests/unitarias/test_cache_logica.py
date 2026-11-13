"""Unitarias de la caché de RF7 (T14, I8): la lógica de `app/cache.py` contra un Redis falso, sin Redis ni base.

Con Redis real, un servidor real y COMMIT de verdad (que reservar y volver a consultar muestre el espacio tomado, que un Redis
caído no tumbe nada) se prueba en test_cache.py. Aquí se prueba cada decisión por separado, y se puede ver el orden exacto de
las operaciones.
"""

import json
import time
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from dobles import FalsoRedis, confirmar, pedido
from redis.exceptions import ConnectionError as RedisCaido

from app import cache

CLINICA, PROFESIONAL, SERVICIO = uuid4(), uuid4(), uuid4()
FECHA = date(2030, 1, 7)
FUTURO = [datetime(2030, 1, 7, 9, tzinfo=timezone.utc), datetime(2030, 1, 7, 9, 15, tzinfo=timezone.utc)]
VERSION = f"disp:version:{PROFESIONAL}"


def clave(version="0", *, clinica=CLINICA, profesional=PROFESIONAL, servicio=SERVICIO, duracion=30, fecha=FECHA):
    return f"disp:{clinica}:{profesional}:v{version}:{servicio}:{duracion}:{fecha}"


def consultar(calcular, **cambios):
    args = {"clinica": CLINICA, "profesional": PROFESIONAL, "servicio": SERVICIO, "duracion": 30, "fecha": FECHA, **cambios}
    return cache.espacios(args["clinica"], args["profesional"], args["servicio"], args["duracion"], args["fecha"], calcular)


@pytest.fixture
def redis(monkeypatch):
    falso = FalsoRedis()
    monkeypatch.setattr(cache, "_redis", lambda: falso)
    return falso


# ---------- Sin copia ----------

def test_sin_redis_se_calcula_siempre_y_no_se_guarda_nada(monkeypatch):
    monkeypatch.setattr(cache, "_redis", lambda: None)
    llamadas = []
    assert consultar(lambda: llamadas.append(1) or FUTURO) == FUTURO
    assert consultar(lambda: llamadas.append(1) or FUTURO) == FUTURO
    assert len(llamadas) == 2


def test_lee_la_version_antes_de_calcular_y_guarda_la_copia_con_esa_version(redis):
    """De este orden depende I8: si la versión se leyera después de calcular, una copia vieja podría guardarse como actual."""
    redis.datos[VERSION] = "7"
    calculos = []
    consultar(lambda: calculos.append(redis.eventos[:]) or FUTURO)
    assert redis.eventos == [("get", VERSION), ("get", clave("7")), ("set", clave("7"))]
    assert calculos == [[("get", VERSION), ("get", clave("7"))]]          # al calcular, la versión ya estaba leída


def test_sin_versión_guardada_arranca_en_cero(redis):
    consultar(lambda: FUTURO)
    assert clave("0") in redis.datos


def test_la_copia_vence_sola_y_se_guarda_como_texto(redis):
    consultar(lambda: FUTURO)
    assert redis.ttl[clave()] == cache.TTL_SEGUNDOS
    assert [datetime.fromisoformat(i) for i in json.loads(redis.datos[clave()])] == FUTURO


# ---------- Con copia ----------

def test_con_copia_no_se_calcula(redis):
    consultar(lambda: FUTURO)
    assert consultar(lambda: pytest.fail("debía salir de la copia")) == FUTURO


def test_de_la_copia_se_quitan_las_horas_que_ya_pasaron(monkeypatch):
    """El tiempo no dispara ninguna invalidación, pero solo quita espacios: basta filtrar al leer."""
    pasada = datetime(2020, 1, 6, 9, tzinfo=timezone.utc)
    redis = FalsoRedis({clave(): json.dumps([pasada.isoformat(), FUTURO[0].isoformat()])})
    monkeypatch.setattr(cache, "_redis", lambda: redis)
    assert consultar(lambda: pytest.fail("debía salir de la copia")) == [FUTURO[0]]


@pytest.mark.parametrize("cambio", [
    {"servicio": uuid4()}, {"duracion": 45}, {"fecha": date(2030, 1, 8)}, {"profesional": uuid4()}, {"clinica": uuid4()},
])
def test_cualquier_dato_de_la_clave_que_cambie_es_otra_copia(redis, cambio):
    consultar(lambda: FUTURO)
    calculos = []
    consultar(lambda: calculos.append(1) or [], **cambio)
    assert calculos == [1]


# ---------- La carrera de I8 ----------

def test_una_copia_tardia_queda_con_la_version_vieja_y_nadie_la_lee(redis):
    """La consulta ya leyó la base cuando alguien reserva e invalida; recién entonces guarda su resultado, ya viejo."""
    def calcular_mientras_alguien_reserva():
        redis.incr(VERSION)
        return FUTURO

    consultar(calcular_mientras_alguien_reserva)
    assert clave("0") in redis.datos                     # guardada con el número viejo…
    nuevo = []
    consultar(lambda: nuevo.append(1) or [])             # …y quien consulta ahora busca el 1: no la encuentra
    assert nuevo == [1]


# ---------- Redis falla ----------

@pytest.mark.parametrize("operacion", ["get", "set"])
def test_si_redis_falla_la_respuesta_sale_igual(redis, operacion):
    redis.fallos[operacion] = RedisCaido("sin conexión")
    assert consultar(lambda: FUTURO) == FUTURO


def test_si_redis_tarda_la_solicitud_no_espera_mas_que_el_limite(redis, monkeypatch):
    monkeypatch.setattr(cache, "LIMITE_SEGUNDOS", 0.05)
    redis.demoras["get"] = 0.5
    inicio = time.perf_counter()
    assert consultar(lambda: FUTURO) == FUTURO
    assert time.perf_counter() - inicio < 0.3


# ---------- Invalidar ----------

def test_invalidar_no_hace_nada_hasta_el_commit(redis):
    request = pedido()
    cache.invalidar_tras_commit(request, PROFESIONAL)
    assert redis.datos == {} and len(request.state.tras_commit) == 1
    confirmar(request)
    assert redis.datos == {VERSION: "1"}


def test_cada_profesional_sube_su_version_una_sola_vez(redis):
    otro, request = uuid4(), pedido()
    cache.invalidar_tras_commit(request, PROFESIONAL, otro, PROFESIONAL)
    confirmar(request)
    assert redis.datos == {VERSION: "1", f"disp:version:{otro}": "1"}


def test_invalidar_sin_redis_no_falla(monkeypatch):
    monkeypatch.setattr(cache, "_redis", lambda: None)
    request = pedido()
    cache.invalidar_tras_commit(request, PROFESIONAL)
    confirmar(request)
