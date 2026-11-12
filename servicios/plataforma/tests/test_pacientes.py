"""RF14: pacientes de la clínica. Escriben administrador y recepción; el profesional solo lee; todo acotado a la clínica
de la sesión (I5); lecturas y escrituras de contacto en la bitácora (RF18)."""

import uuid

import pytest

from conftest import como


def datos(**cambios):
    return {"identificacion": f"1-{uuid.uuid4().int % 10**8:08d}", "nombre": "Ana Solís", "fecha_nacimiento": "1990-05-17",
            "telefono": "8888-1234", "correo": "Ana@Correo.com", **cambios}


def alta(cliente, quien, **cambios):
    return cliente.post("/pacientes", json=datos(**cambios), headers=como(quien))


def bitacora(con, paciente_id):
    return con.execute("SELECT accion, recurso, usuario_id FROM registro_auditoria WHERE paciente_id = %s ORDER BY id",
                       (paciente_id,)).fetchall()


# ---------- permisos ----------

def test_sin_sesion_recibe_401(cliente):
    assert cliente.get("/pacientes").status_code == 401


def test_plataforma_recibe_403_en_todo(cliente, mundo):
    h = como(mundo.plataforma)
    assert cliente.get("/pacientes", headers=h).status_code == 403
    assert cliente.post("/pacientes", json=datos(), headers=h).status_code == 403


def test_profesional_solo_lee(cliente, mundo):
    p = alta(cliente, mundo.recepcion).json()
    h = como(mundo.profesional)
    assert cliente.get("/pacientes", headers=h).status_code == 200
    assert cliente.get(f"/pacientes/{p['id']}", headers=h).status_code == 200
    assert cliente.post("/pacientes", json=datos(), headers=h).status_code == 403
    assert cliente.put(f"/pacientes/{p['id']}", json=datos(), headers=h).status_code == 403


@pytest.mark.parametrize("quien", ["admin_clinica", "recepcion"])
def test_administrador_y_recepcion_escriben(cliente, mundo, quien):
    assert alta(cliente, getattr(mundo, quien)).status_code == 201


# ---------- registrar y actualizar ----------

def test_registrar_normaliza_y_guarda_en_la_clinica_de_la_sesion(cliente, con, mundo):
    r = alta(cliente, mundo.recepcion, nombre="  Ana   Solís ", telefono="")
    assert r.status_code == 201
    p = r.json()
    assert p["correo"] == "ana@correo.com" and p["telefono"] is None
    fila = con.execute("SELECT clinica_id FROM paciente WHERE id = %s", (p["id"],)).fetchone()
    assert fila["clinica_id"] == mundo.clinica_id


def test_identificacion_repetida_da_409_pero_en_otra_clinica_se_permite(cliente, mundo):
    d = datos()
    assert cliente.post("/pacientes", json=d, headers=como(mundo.recepcion)).status_code == 201
    assert cliente.post("/pacientes", json=d, headers=como(mundo.recepcion)).status_code == 409
    assert cliente.post("/pacientes", json=d, headers=como(mundo.recepcion_otra)).status_code == 201


def test_actualizar_cambia_los_datos(cliente, mundo):
    p = alta(cliente, mundo.recepcion).json()
    r = cliente.put(f"/pacientes/{p['id']}", json=datos(identificacion=p["identificacion"], nombre="Ana María Solís"),
                    headers=como(mundo.admin_clinica))
    assert r.status_code == 200 and r.json()["nombre"] == "Ana María Solís"


def test_actualizar_con_identificacion_de_otro_paciente_da_409(cliente, mundo):
    a, b = alta(cliente, mundo.recepcion).json(), alta(cliente, mundo.recepcion).json()
    r = cliente.put(f"/pacientes/{b['id']}", json=datos(identificacion=a["identificacion"]), headers=como(mundo.recepcion))
    assert r.status_code == 409


@pytest.mark.parametrize("malo", [
    {"identificacion": "ab"}, {"nombre": "Al"}, {"fecha_nacimiento": "2999-01-01"}, {"fecha_nacimiento": "1850-01-01"},
    {"fecha_nacimiento": "2026-02-31"}, {"telefono": "abc"}, {"correo": "sin-arroba"},
    {"clinica_id": str(uuid.uuid4())}, {"id": str(uuid.uuid4())},
])
def test_datos_invalidos_dan_422(cliente, mundo, malo):
    assert alta(cliente, mundo.recepcion, **malo).status_code == 422


def test_entrada_mal_formada_no_rompe_el_servicio(cliente, mundo):
    h = como(mundo.recepcion)
    assert cliente.post("/pacientes", content="{no es json", headers={**h, "Content-Type": "application/json"}).status_code == 422
    assert cliente.get("/pacientes/no-es-uuid", headers=h).status_code == 422
    assert cliente.get("/pacientes", headers=h).status_code == 200


# ---------- aislamiento (I5) ----------

def test_otra_clinica_responde_404_y_no_aparece_en_el_listado(cliente, mundo):
    ajeno = alta(cliente, mundo.recepcion_otra, nombre="Paciente Ajeno").json()
    h = como(mundo.recepcion)
    assert cliente.get(f"/pacientes/{ajeno['id']}", headers=h).status_code == 404
    assert cliente.put(f"/pacientes/{ajeno['id']}", json=datos(), headers=h).status_code == 404
    lista = cliente.get("/pacientes", params={"q": "Ajeno", "clinica_id": str(mundo.clinica_id)}, headers=h).json()
    assert lista["total"] == 0 and lista["pacientes"] == []


# ---------- listado ----------

def test_listado_no_trae_contacto_ni_audita(cliente, con, mundo):
    p = alta(cliente, mundo.recepcion, nombre="Zoila Listable").json()
    n = con.execute("SELECT count(*) AS n FROM registro_auditoria").fetchone()["n"]
    lista = cliente.get("/pacientes", params={"q": "listable"}, headers=como(mundo.recepcion)).json()
    assert [x["id"] for x in lista["pacientes"]] == [p["id"]]
    assert "telefono" not in lista["pacientes"][0] and "correo" not in lista["pacientes"][0]
    assert con.execute("SELECT count(*) AS n FROM registro_auditoria").fetchone()["n"] == n


def test_los_comodines_se_buscan_literalmente(cliente, mundo):
    alta(cliente, mundo.recepcion, nombre="Pedro Pérez")
    assert cliente.get("/pacientes", params={"q": "%"}, headers=como(mundo.recepcion)).json()["total"] == 0


# ---------- bitácora (RF18) ----------

def test_escrituras_y_lecturas_de_la_ficha_quedan_en_la_bitacora(cliente, con, mundo):
    p = alta(cliente, mundo.recepcion).json()
    cliente.put(f"/pacientes/{p['id']}", json=datos(identificacion=p["identificacion"]), headers=como(mundo.admin_clinica))
    cliente.get(f"/pacientes/{p['id']}", headers=como(mundo.profesional))
    filas = bitacora(con, p["id"])
    assert [(f["accion"], f["recurso"]) for f in filas] == [("ESCRITURA", "CONTACTO_PACIENTE")] * 2 + [("LECTURA", "CONTACTO_PACIENTE")]
    assert [f["usuario_id"] for f in filas] == [mundo.recepcion, mundo.admin_clinica, mundo.profesional]


def test_un_rechazo_no_deja_registro(cliente, con, mundo):
    p = alta(cliente, mundo.recepcion).json()
    n = len(bitacora(con, p["id"]))
    cliente.put(f"/pacientes/{p['id']}", json=datos(nombre="x"), headers=como(mundo.recepcion))
    cliente.get(f"/pacientes/{p['id']}", headers=como(mundo.recepcion_otra))
    assert len(bitacora(con, p["id"])) == n
