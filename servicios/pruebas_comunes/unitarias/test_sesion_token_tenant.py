"""T33: unitarias del token (RF17) y de la clínica que sale de la sesión (I5), SIN base de datos ni Keycloak.

Prueban `medicitas_comun.sesion`, que usan los tres servicios; el Dockerfile copia este archivo a `tests/unitarias/` de
cada uno. Los dobles: llaves RSA generadas aquí en lugar de las del realm, y una «conexión» que solo anota lo que se le pide.
Que el motor y la API completa respondan igual (401/403 con tokens reales contra filas reales) lo prueba
`permisos.py` (T29), con base; aquí se prueba la lógica de decisión por sí sola.
"""

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.exceptions import PyJWKClientConnectionError

from medicitas_comun import Sesion, sesion_actual, sesion_de_clinica
from medicitas_comun import sesion as modulo

EMISOR = "http://keycloak.prueba/realms/medicitas"


# ---------- Dobles ----------

class JWKSFalso:
    """Hace de las llaves públicas del realm; `caido` simula que no se pueden consultar."""

    def __init__(self, publica, caido=False):
        self.publica, self.caido = publica, caido

    def get_signing_key_from_jwt(self, token):
        if self.caido:
            raise PyJWKClientConnectionError("sin conexión")
        return SimpleNamespace(key=self.publica)


class ConexionFalsa:
    """Responde con `fila` a cualquier consulta y anota (sql, params) de cada una."""

    def __init__(self, fila):
        self.fila, self.consultas = fila, []

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        return self

    def fetchone(self):
        return self.fila


@pytest.fixture(scope="module")
def llaves():
    return [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]


@pytest.fixture
def keycloak(monkeypatch, llaves):
    """AUTH_MODO=keycloak con el emisor de la prueba y las llaves públicas de `llaves[0]`."""
    monkeypatch.setenv("AUTH_MODO", "keycloak")
    monkeypatch.setenv("KEYCLOAK_ISSUER", EMISOR)
    monkeypatch.setattr(modulo, "_cliente_jwks", lambda: JWKSFalso(llaves[0].public_key()))


def token(llaves, firma=0, **cambios):
    """Un token de acceso válido; `cambios` lo estropea (un valor None quita ese campo)."""
    datos = {"sub": str(uuid.uuid4()), "iss": EMISOR, "typ": "Bearer", "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **cambios}
    return jwt.encode({k: v for k, v in datos.items() if v is not None}, llaves[firma], algorithm="RS256")


def codigo_de(funcion, *args, **kwargs) -> int:
    with pytest.raises(HTTPException) as e:
        funcion(*args, **kwargs)
    return e.value.status_code


# ---------- Validar el token: qué se acepta y qué no (RF17) ----------

def test_un_token_en_regla_entrega_su_sub(keycloak, llaves):
    sub = str(uuid.uuid4())
    assert modulo._sub_del_token(f"Bearer {token(llaves, sub=sub)}") == sub


def test_el_esquema_bearer_no_distingue_mayusculas(keycloak, llaves):
    assert modulo._sub_del_token(f"bEaReR {token(llaves, sub='abc')}") == "abc"


def casos_401(llaves):
    ahora = datetime.now(timezone.utc)
    return {
        "sin cabecera": None,
        "cabecera vacía": "",
        "otro esquema (Basic)": f"Basic {token(llaves)}",
        "Bearer sin token": "Bearer ",
        "texto que no es un JWT": "Bearer esto-no-es-un-token",
        "firmado con otra llave": f"Bearer {token(llaves, firma=1)}",
        "vencido": f"Bearer {token(llaves, exp=ahora - timedelta(minutes=1))}",
        "de otro emisor": f"Bearer {token(llaves, iss='http://otro.idp/realms/x')}",
        "sin emisor": f"Bearer {token(llaves, iss=None)}",
        "un id_token y no uno de acceso": f"Bearer {token(llaves, typ='ID')}",
        "sin typ": f"Bearer {token(llaves, typ=None)}",
        "sin sub": f"Bearer {token(llaves, sub=None)}",
        "sub vacío": f"Bearer {token(llaves, sub='')}",
        "sin firma (alg none)": "Bearer " + jwt.encode({"sub": "x", "iss": EMISOR, "typ": "Bearer"}, None, algorithm="none"),
    }


def test_todo_token_que_no_se_puede_confiar_responde_401(keycloak, llaves):
    obtenidos = {caso: codigo_de(modulo._sub_del_token, aut) for caso, aut in casos_401(llaves).items()}
    assert set(obtenidos.values()) == {401}, {c: v for c, v in obtenidos.items() if v != 401}


def test_si_no_se_pueden_consultar_las_llaves_es_503_y_no_401(monkeypatch, keycloak, llaves):
    """El token puede ser válido: no es culpa del cliente que no se haya podido comprobar."""
    monkeypatch.setattr(modulo, "_cliente_jwks", lambda: JWKSFalso(None, caido=True))
    assert codigo_de(modulo._sub_del_token, f"Bearer {token(llaves)}") == 503


def test_el_mensaje_del_401_no_revela_la_llave_ni_el_token(keycloak, llaves):
    malo = token(llaves, firma=1)
    with pytest.raises(HTTPException) as e:
        modulo._sub_del_token(f"Bearer {malo}")
    assert malo not in e.value.detail


# ---------- Quién es la sesión según el modo (AUTH_MODO) ----------

USUARIO = uuid.uuid4()
CLINICA = uuid.uuid4()


def fila(activo=True, clinica=CLINICA, rol="RECEPCION"):
    return {"id": USUARIO, "clinica_id": clinica, "rol": rol, "activo": activo}


def test_en_modo_keycloak_se_busca_al_usuario_por_el_sub_del_token(keycloak, llaves):
    con, sub = ConexionFalsa(fila()), str(uuid.uuid4())
    sesion = sesion_actual(authorization=f"Bearer {token(llaves, sub=sub)}", x_usuario_id=None, con=con)
    assert sesion == Sesion(USUARIO, CLINICA, "RECEPCION")
    (sql, params), = con.consultas
    assert "keycloak_sub = %s" in sql and params == (sub,)


def test_en_modo_keycloak_la_cabecera_X_Usuario_Id_no_suplanta_a_nadie(keycloak, llaves):
    """Quien manda X-Usuario-Id con un token válido sigue siendo el dueño del token, no el de la cabecera."""
    con, sub, otro = ConexionFalsa(fila()), str(uuid.uuid4()), uuid.uuid4()
    sesion_actual(authorization=f"Bearer {token(llaves, sub=sub)}", x_usuario_id=str(otro), con=con)
    assert con.consultas[0][1] == (sub,)


def test_en_modo_keycloak_sin_token_no_se_consulta_la_base(keycloak):
    con = ConexionFalsa(fila())
    assert codigo_de(sesion_actual, authorization=None, x_usuario_id=str(USUARIO), con=con) == 401
    assert con.consultas == []


def test_en_modo_desarrollo_se_busca_por_id(monkeypatch):
    monkeypatch.setenv("AUTH_MODO", "desarrollo")
    con = ConexionFalsa(fila())
    assert sesion_actual(authorization=None, x_usuario_id=str(USUARIO), con=con).usuario_id == USUARIO
    (sql, params), = con.consultas
    assert "u.id = %s" in sql and params == (USUARIO,)


@pytest.mark.parametrize("cabecera", [None, "", "no-es-un-id", "123", str(USUARIO) + "x"])
def test_en_modo_desarrollo_una_cabecera_que_no_es_un_uuid_es_401(monkeypatch, cabecera):
    monkeypatch.setenv("AUTH_MODO", "desarrollo")
    con = ConexionFalsa(fila())
    assert codigo_de(sesion_actual, authorization=None, x_usuario_id=cabecera, con=con) == 401
    assert con.consultas == []


@pytest.mark.parametrize("modo", [None, "", "produccion", "KEYCLOAK", "Desarrollo"])
def test_con_un_modo_desconocido_o_sin_configurar_se_rechaza_todo(monkeypatch, modo):
    """Fallar cerrado: un error de configuración no debe dejar pasar a nadie."""
    if modo is None:
        monkeypatch.delenv("AUTH_MODO", raising=False)
    else:
        monkeypatch.setenv("AUTH_MODO", modo)
    con = ConexionFalsa(fila())
    assert codigo_de(sesion_actual, authorization="Bearer x", x_usuario_id=str(USUARIO), con=con) == 401
    assert con.consultas == []


def test_un_usuario_que_no_existe_es_401(monkeypatch):
    monkeypatch.setenv("AUTH_MODO", "desarrollo")
    assert codigo_de(sesion_actual, authorization=None, x_usuario_id=str(uuid.uuid4()), con=ConexionFalsa(None)) == 401


def test_un_usuario_dado_de_baja_es_403_aunque_su_token_siga_vigente(keycloak, llaves):
    """Se consulta en cada solicitud: la baja lógica corta el acceso sin esperar a que el token expire."""
    con = ConexionFalsa(fila(activo=False))
    assert codigo_de(sesion_actual, authorization=f"Bearer {token(llaves)}", x_usuario_id=None, con=con) == 403


# ---------- La clínica sale de la sesión (I5) ----------

def test_la_clinica_de_la_sesion_es_la_de_la_base_y_no_otra(monkeypatch):
    monkeypatch.setenv("AUTH_MODO", "desarrollo")
    sesion = sesion_actual(authorization=None, x_usuario_id=str(USUARIO), con=ConexionFalsa(fila(clinica=CLINICA)))
    assert sesion.clinica_id == CLINICA


def test_la_sesion_no_se_puede_modificar_una_vez_creada():
    sesion = Sesion(USUARIO, CLINICA, "RECEPCION")
    with pytest.raises(FrozenInstanceError):
        sesion.clinica_id = uuid.uuid4()


def test_quien_no_pertenece_a_una_clinica_no_pasa_por_sesion_de_clinica():
    """El administrador de plataforma no ve datos clínicos: sin clínica, 403."""
    assert codigo_de(sesion_de_clinica, Sesion(USUARIO, None, "ADM_PLATAFORMA")) == 403


def test_quien_pertenece_a_una_clinica_pasa_igual_que_entro():
    sesion = Sesion(USUARIO, CLINICA, "RECEPCION")
    assert sesion_de_clinica(sesion) is sesion


def _parametros_de_entrada(app):
    """(ruta, nombre) de todo lo que el cliente puede mandar: camino, consulta, cabeceras y campos del cuerpo."""
    esquema = app.openapi()
    for camino, operaciones in esquema["paths"].items():
        for metodo, op in operaciones.items():
            for p in op.get("parameters", []):
                yield f"{metodo.upper()} {camino}", p["name"]
            cuerpo = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            ref = cuerpo.get("$ref", "").rsplit("/", 1)[-1]
            for campo in esquema["components"]["schemas"].get(ref, {}).get("properties", {}):
                yield f"{metodo.upper()} {camino}", campo


def test_ninguna_ruta_deja_que_el_cliente_elija_la_clinica_I5():
    """Ni como parámetro de la ruta, de la consulta o de una cabecera, ni como campo del cuerpo: la clínica es la de la sesión."""
    from app.main import app

    prohibidos = {"clinica_id", "clinica", "tenant", "tenant_id", "x-clinica-id"}
    ofensas = [f"{ruta}: {nombre}" for ruta, nombre in _parametros_de_entrada(app) if nombre.lower() in prohibidos]
    assert ofensas == []
