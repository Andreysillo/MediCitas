"""T35 (unitarias): cómo traduce `crear_app` los errores, SIN base de datos.

RO3 del enunciado: «el servicio no se interrumpe ante una entrada mal formada ni ante un recurso inexistente, sino que
responde con el código que corresponde y permanece operativo». Aquí se arma una app mínima con `crear_app` y rutas que
fallan de cada manera; la API real, ruta por ruta y con base, la ejercita `errores.py` (test_errores.py de cada servicio).
No se entra al ciclo de vida de la app (no se abre ningún pool): solo se prueban sus manejadores de errores.
"""

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import errors
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict

from medicitas_comun import crear_app


class Datos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str
    edad: int


def _explota(excepcion):
    def ruta():
        raise excepcion
    return ruta


FALLAS = {
    "/no-existe-en-la-base": HTTPException(404, "No encontrado"),
    "/solape": errors.ExclusionViolation(),
    "/repetido": errors.UniqueViolation(),
    "/referencia": errors.ForeignKeyViolation(),
    "/regla": errors.CheckViolation(),
    "/deadlock": errors.DeadlockDetected(),
    "/bloqueo-largo": errors.LockNotAvailable(),
    "/serializacion": errors.SerializationFailure(),
    "/dato-fuera-de-rango": errors.DataError(),
    "/fecha-fuera-de-rango": OverflowError("year 10000 is out of range"),
    "/base-caida": psycopg.OperationalError("connection refused"),
    "/pool-agotado": PoolTimeout(),
    "/error-inesperado": RuntimeError("secreto: password=hunter2"),
}


@pytest.fixture(scope="module")
def cliente():
    app = crear_app("prueba")
    for camino, excepcion in FALLAS.items():
        app.get(camino)(_explota(excepcion))

    @app.get("/uno/{numero}")
    def uno(numero: int):
        return {"numero": numero}

    @app.post("/datos")
    def datos(d: Datos):
        return d

    # raise_server_exceptions=False: como en producción, un error no controlado llega al cliente como respuesta.
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("camino, estado", [
    ("/no-existe-en-la-base", 404),
    ("/solape", 409), ("/repetido", 409),
    ("/referencia", 422), ("/regla", 422),
    ("/dato-fuera-de-rango", 422), ("/fecha-fuera-de-rango", 422),
    ("/deadlock", 503), ("/bloqueo-largo", 503), ("/serializacion", 503),
    ("/base-caida", 503), ("/pool-agotado", 503),
    ("/error-inesperado", 500),
])
def test_cada_falla_responde_el_codigo_que_le_corresponde(cliente, camino, estado):
    assert cliente.get(camino).status_code == estado


def test_toda_respuesta_de_error_trae_el_campo_detalle(cliente):
    for camino in FALLAS:
        r = cliente.get(camino)
        assert "detalle" in r.json(), f"{camino}: {r.text}"


def test_un_error_inesperado_no_filtra_el_mensaje_ni_la_traza_pero_si_un_id_para_rastrearlo(cliente):
    r = cliente.get("/error-inesperado", headers={"x-request-id": "abc123"})
    assert r.json() == {"detalle": "Error interno", "solicitud": "abc123"}
    assert "hunter2" not in r.text and "Traceback" not in r.text


def test_el_servicio_sigue_atendiendo_despues_de_cada_falla(cliente):
    for camino in FALLAS:
        cliente.get(camino)
        assert cliente.get("/salud").status_code == 200, f"el servicio dejó de responder tras {camino}"
        assert cliente.get("/uno/7").json() == {"numero": 7}


def test_los_errores_transitorios_piden_reintentar(cliente):
    assert cliente.get("/deadlock").headers["retry-after"] == "1"


# ---------- Entrada mal formada ----------

@pytest.mark.parametrize("numero", ["abc", "1.5", "%20", "--1", "1e3"])
def test_un_parametro_de_ruta_que_no_es_del_tipo_es_422_y_no_500(cliente, numero):
    assert cliente.get(f"/uno/{numero}").status_code in (404, 422)


@pytest.mark.parametrize("contenido", [b'{"nombre": ', b"no es json", b"", b"[]", b"null", b"\xff\xfe", b'"texto"'])
def test_un_cuerpo_roto_o_de_otra_forma_es_422(cliente, contenido):
    r = cliente.post("/datos", content=contenido, headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text
    assert "detalle" in r.json()


@pytest.mark.parametrize("cuerpo", [
    {}, {"nombre": "Ana"}, {"nombre": 1, "edad": "x"}, {"nombre": "Ana", "edad": 30, "clinica_id": "otra"},
    {"nombre": None, "edad": None}, {"nombre": "Ana", "edad": [1]},
])
def test_campos_que_faltan_sobran_o_son_de_otro_tipo_son_422(cliente, cuerpo):
    assert cliente.post("/datos", json=cuerpo).status_code == 422


def test_el_422_dice_cuales_campos_fallaron(cliente):
    r = cliente.post("/datos", json={"nombre": "Ana", "edad": "x"})
    assert [c["campo"] for c in r.json()["campos"]] == ["edad"]


def test_una_ruta_que_no_existe_es_404_y_un_metodo_no_permitido_es_405(cliente):
    assert cliente.get("/no-hay-tal-ruta").status_code == 404
    assert cliente.delete("/uno/1").status_code == 405
