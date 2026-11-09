"""RF1: alta de una clínica con su primer administrador. Matriz de permisos: solo el administrador de plataforma."""

import uuid

import pytest

from conftest import como


def cuerpo(**cambios):
    n = uuid.uuid4().hex[:8]
    base = {
        "nombre": "Clínica Central",
        "identificador": f"central-{n}",
        "zona_horaria": "America/Costa_Rica",
        "admin_nombre": "Ana Mora",
        "admin_usuario": f"admin-{n}",
        "admin_contrasena": "temporal-123",
    }
    return {**base, **cambios}


def test_crea_la_clinica_y_su_administrador(cliente, con, mundo, kc):
    datos = cuerpo()
    r = cliente.post("/clinicas", json=datos, headers=como(mundo.plataforma))
    assert r.status_code == 201, r.text
    salida = r.json()
    assert salida["clinica"]["identificador"] == datos["identificador"]
    assert salida["clinica"]["zona_horaria"] == "America/Costa_Rica"
    assert salida["admin"]["rol"] == "ADM_CLINICA" and salida["admin"]["activo"] is True
    assert "contrasena" not in r.text and "temporal-123" not in r.text  # la contraseña nunca vuelve

    fila = con.execute(
        "SELECT u.clinica_id, u.keycloak_sub, r.codigo FROM usuario u JOIN rol r ON r.id = u.rol_id WHERE u.id = %s",
        (salida["admin"]["id"],),
    ).fetchone()
    assert str(fila["clinica_id"]) == salida["clinica"]["id"] and fila["codigo"] == "ADM_CLINICA"
    assert [fila["keycloak_sub"]] == [c["sub"] for c in kc.creados]  # el sub es el que emitió Keycloak
    assert kc.creados[0]["rol"] == "ADM_CLINICA"


@pytest.mark.parametrize("rol", ["admin_clinica", "recepcion", "profesional"])
def test_otros_roles_reciben_403_y_no_se_crea_nada(cliente, con, mundo, kc, rol):
    datos = cuerpo()
    r = cliente.post("/clinicas", json=datos, headers=como(getattr(mundo, rol)))
    assert r.status_code == 403
    assert kc.creados == []
    assert con.execute("SELECT 1 FROM clinica WHERE identificador = %s", (datos["identificador"],)).fetchone() is None


def test_sin_sesion_recibe_401(cliente, kc):
    assert cliente.post("/clinicas", json=cuerpo()).status_code == 401
    assert kc.creados == []


def test_identificador_repetido_es_409_y_no_toca_keycloak(cliente, mundo, kc):
    datos = cuerpo()
    assert cliente.post("/clinicas", json=datos, headers=como(mundo.plataforma)).status_code == 201
    kc.creados.clear()
    r = cliente.post("/clinicas", json={**datos, "admin_usuario": "otro-admin"}, headers=como(mundo.plataforma))
    assert r.status_code == 409
    assert kc.creados == []


def test_si_keycloak_cae_no_queda_clinica_a_medias(cliente, con, mundo, kc):
    kc.falla = "caido"
    datos = cuerpo()
    r = cliente.post("/clinicas", json=datos, headers=como(mundo.plataforma))
    assert r.status_code == 503
    assert con.execute("SELECT 1 FROM clinica WHERE identificador = %s", (datos["identificador"],)).fetchone() is None


def test_usuario_repetido_en_keycloak_es_409_sin_clinica(cliente, con, mundo, kc):
    kc.falla = "repetido"
    datos = cuerpo()
    assert cliente.post("/clinicas", json=datos, headers=como(mundo.plataforma)).status_code == 409
    assert con.execute("SELECT 1 FROM clinica WHERE identificador = %s", (datos["identificador"],)).fetchone() is None


@pytest.mark.parametrize("cambio", [
    {"identificador": "Con Espacios"},
    {"identificador": "ab"},
    {"zona_horaria": "Marte/Olympus"},
    {"nombre": "  "},
    {"admin_contrasena": "corta"},
    {"clinica_id": str(uuid.uuid4())},  # campo que no existe: se rechaza, no se ignora
])
def test_datos_invalidos_son_422(cliente, con, mundo, kc, cambio):
    r = cliente.post("/clinicas", json=cuerpo(**cambio), headers=como(mundo.plataforma))
    assert r.status_code == 422
    assert kc.creados == []


def test_listado_solo_para_plataforma(cliente, mundo):
    assert cliente.get("/clinicas", headers=como(mundo.plataforma)).status_code == 200
    assert cliente.get("/clinicas", headers=como(mundo.admin_clinica)).status_code == 403
