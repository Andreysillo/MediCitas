"""RF3: catálogo de servicios (y las especialidades que necesitan). Solo el administrador de la clínica; la clínica sale
de la sesión y nada de otra clínica es visible ni utilizable (I5)."""

import uuid

import pytest

from conftest import como


@pytest.fixture
def especialidad(con, mundo):
    return con.execute("SELECT id FROM especialidad WHERE clinica_id = %s", (mundo.clinica_id,)).fetchone()["id"]


@pytest.fixture
def especialidad_ajena(con, mundo):
    """Una especialidad de OTRA clínica."""
    otra = con.execute("SELECT clinica_id FROM usuario WHERE id = %s", (mundo.admin_otra,)).fetchone()["clinica_id"]
    return con.execute("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'Ajena') RETURNING id", (otra,)).fetchone()["id"]


def servicio(especialidad, **cambios):
    return {"nombre": f"Consulta {uuid.uuid4().hex[:6]}", "duracion_minutos": 30, "especialidad_id": str(especialidad), **cambios}


# ---------- permisos ----------

@pytest.mark.parametrize("quien", ["recepcion", "profesional", "plataforma"])
def test_otros_roles_reciben_403(cliente, mundo, especialidad, quien):
    h = como(getattr(mundo, quien))
    assert cliente.get("/servicios", headers=h).status_code == 403
    assert cliente.post("/servicios", json=servicio(especialidad), headers=h).status_code == 403
    assert cliente.get("/especialidades", headers=h).status_code == 403
    assert cliente.post("/especialidades", json={"nombre": "Pediatría"}, headers=h).status_code == 403


def test_sin_sesion_recibe_401(cliente):
    assert cliente.get("/servicios").status_code == 401


# ---------- servicios ----------

def test_crear_servicio(cliente, mundo, especialidad):
    r = cliente.post("/servicios", json=servicio(especialidad, duracion_minutos=45), headers=como(mundo.admin_clinica))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["duracion_minutos"] == 45 and s["activo"] is True and s["especialidad"] == "General"
    assert s["id"] in {x["id"] for x in cliente.get("/servicios", headers=como(mundo.admin_clinica)).json()}


@pytest.mark.parametrize("cambio", [
    {"duracion_minutos": 0}, {"duracion_minutos": 4}, {"duracion_minutos": 481}, {"duracion_minutos": 30.5},
    {"duracion_minutos": "treinta"}, {"nombre": " "}, {"nombre": "x" * 61}, {"clinica_id": str(uuid.uuid4())},
])
def test_datos_invalidos_son_422(cliente, mundo, especialidad, cambio):
    assert cliente.post("/servicios", json=servicio(especialidad, **cambio), headers=como(mundo.admin_clinica)).status_code == 422


def test_nombre_repetido_es_409(cliente, mundo, especialidad):
    h = como(mundo.admin_clinica)
    datos = servicio(especialidad)
    assert cliente.post("/servicios", json=datos, headers=h).status_code == 201
    assert cliente.post("/servicios", json=datos, headers=h).status_code == 409


def test_especialidad_de_otra_clinica_es_422(cliente, mundo, especialidad_ajena):
    r = cliente.post("/servicios", json=servicio(especialidad_ajena), headers=como(mundo.admin_clinica))
    assert r.status_code == 422


def test_especialidad_inexistente_es_422(cliente, mundo):
    assert cliente.post("/servicios", json=servicio(uuid.uuid4()), headers=como(mundo.admin_clinica)).status_code == 422


def test_listado_no_trae_servicios_de_otra_clinica(cliente, con, mundo, especialidad_ajena):
    otra = con.execute("SELECT clinica_id FROM especialidad WHERE id = %s", (especialidad_ajena,)).fetchone()["clinica_id"]
    ajeno = con.execute(
        "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, 'Ajeno', 20, %s) RETURNING id",
        (otra, especialidad_ajena)).fetchone()["id"]
    r = cliente.get("/servicios", headers=como(mundo.admin_clinica))
    assert str(ajeno) not in {s["id"] for s in r.json()}


def test_actualizar_servicio(cliente, mundo, especialidad):
    h = como(mundo.admin_clinica)
    s = cliente.post("/servicios", json=servicio(especialidad), headers=h).json()
    r = cliente.patch(f"/servicios/{s['id']}", json={"nombre": "Control", "duracion_minutos": 20, "activo": False}, headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["nombre"], r.json()["duracion_minutos"], r.json()["activo"]) == ("Control", 20, False)
    assert r.json()["especialidad_id"] == s["especialidad_id"]  # no cambia


def test_actualizar_con_nombre_de_otro_servicio_es_409(cliente, mundo, especialidad):
    h = como(mundo.admin_clinica)
    a = cliente.post("/servicios", json=servicio(especialidad), headers=h).json()
    b = cliente.post("/servicios", json=servicio(especialidad), headers=h).json()
    r = cliente.patch(f"/servicios/{b['id']}", json={"nombre": a["nombre"], "duracion_minutos": 30, "activo": True}, headers=h)
    assert r.status_code == 409


def test_servicio_de_otra_clinica_o_inexistente_responde_404(cliente, con, mundo, especialidad_ajena):
    otra = con.execute("SELECT clinica_id FROM especialidad WHERE id = %s", (especialidad_ajena,)).fetchone()["clinica_id"]
    ajeno = con.execute(
        "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, 'Ajeno', 20, %s) RETURNING id",
        (otra, especialidad_ajena)).fetchone()["id"]
    h = como(mundo.admin_clinica)
    cuerpo = {"nombre": "Hackeado", "duracion_minutos": 10, "activo": False}
    assert cliente.patch(f"/servicios/{ajeno}", json=cuerpo, headers=h).status_code == 404
    assert cliente.patch(f"/servicios/{uuid.uuid4()}", json=cuerpo, headers=h).status_code == 404
    assert cliente.patch("/servicios/no-es-uuid", json=cuerpo, headers=h).status_code == 422
    fila = con.execute("SELECT nombre, activo FROM servicio WHERE id = %s", (ajeno,)).fetchone()
    assert (fila["nombre"], fila["activo"]) == ("Ajeno", True)  # intacto


def test_cambiar_la_duracion_no_altera_citas_existentes(cliente, con, mundo, especialidad):
    """I4: cada cita guarda su `fin`; editar el servicio solo afecta a las nuevas."""
    h = como(mundo.admin_clinica)
    s = cliente.post("/servicios", json=servicio(especialidad, duracion_minutos=30), headers=h).json()
    prof = con.execute("SELECT id FROM profesional WHERE usuario_id = %s", (mundo.profesional,)).fetchone()["id"]
    con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)", (mundo.clinica_id, prof, s["id"]))
    pac = con.execute("INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s,'9-9','P','1990-01-01') RETURNING id",
                      (mundo.clinica_id,)).fetchone()["id"]
    cita = con.execute(
        """INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por)
           VALUES (%s,%s,%s,%s, now() + interval '3 days', now() + interval '3 days 30 minutes', 'RESERVADA', %s) RETURNING id, fin""",
        (mundo.clinica_id, pac, prof, s["id"], mundo.admin_clinica)).fetchone()
    assert cliente.patch(f"/servicios/{s['id']}", json={"nombre": s["nombre"], "duracion_minutos": 60, "activo": True}, headers=h).status_code == 200
    assert con.execute("SELECT fin FROM cita WHERE id = %s", (cita["id"],)).fetchone()["fin"] == cita["fin"]


# ---------- especialidades ----------

def test_crear_y_listar_especialidades(cliente, mundo):
    h = como(mundo.admin_clinica)
    r = cliente.post("/especialidades", json={"nombre": "Pediatría"}, headers=h)
    assert r.status_code == 201
    assert "Pediatría" in {e["nombre"] for e in cliente.get("/especialidades", headers=h).json()}
    assert cliente.post("/especialidades", json={"nombre": "Pediatría"}, headers=h).status_code == 409


def test_especialidades_de_otra_clinica_no_se_ven(cliente, mundo, especialidad_ajena):
    ids = {e["id"] for e in cliente.get("/especialidades", headers=como(mundo.admin_clinica)).json()}
    assert str(especialidad_ajena) not in ids
