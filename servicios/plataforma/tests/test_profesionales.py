"""RF4: profesionales con su especialidad y los servicios que atienden. Solo el administrador de la clínica; todo se
acota a la clínica de la sesión (I5)."""

import uuid

import pytest

from conftest import _usuario, como


@pytest.fixture
def general(con, mundo):
    return con.execute("SELECT id FROM especialidad WHERE clinica_id = %s AND nombre = 'General'", (mundo.clinica_id,)).fetchone()["id"]


@pytest.fixture
def pediatria(con, mundo):
    return con.execute("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'Pediatría') RETURNING id", (mundo.clinica_id,)).fetchone()["id"]


def un_servicio(con, clinica_id, especialidad, nombre=None):
    return con.execute(
        "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, %s, 30, %s) RETURNING id",
        (clinica_id, nombre or f"S-{uuid.uuid4().hex[:6]}", especialidad)).fetchone()["id"]


@pytest.fixture
def libre(con, mundo):
    """Un usuario PROFESIONAL activo sin registro de profesional."""
    return _usuario(con, "PROFESIONAL", mundo.clinica_id)


def datos(general, servicios=(), **cambios):
    return {"especialidad_id": str(general), "numero_colegiado": "COL-123", "servicios_ids": [str(s) for s in servicios], **cambios}


def alta(cliente, mundo, libre, general, servicios=(), **cambios):
    return cliente.post("/profesionales", json={"usuario_id": str(libre), **datos(general, servicios, **cambios)},
                        headers=como(mundo.admin_clinica))


# ---------- permisos ----------

@pytest.mark.parametrize("quien", ["recepcion", "profesional"])
def test_recepcion_y_profesional_leen_la_lista_pero_no_la_modifican(cliente, mundo, libre, general, quien):
    """Leer la lista amplía la matriz (ver catalogo.py): recepción la necesita para reservar. Registrar y editar, no."""
    h = como(getattr(mundo, quien))
    r = cliente.get("/profesionales", headers=h)
    de_admin = cliente.get("/profesionales", headers=como(mundo.admin_clinica)).json()
    assert r.status_code == 200 and r.json() == de_admin and de_admin      # la misma lista, y el mundo trae un profesional
    assert cliente.post("/profesionales", json={"usuario_id": str(libre), **datos(general)}, headers=h).status_code == 403


@pytest.mark.parametrize("quien", ["recepcion", "profesional", "plataforma"])
def test_otros_roles_reciben_403(cliente, mundo, libre, general, quien):
    h = como(getattr(mundo, quien))
    if quien == "plataforma":
        assert cliente.get("/profesionales", headers=h).status_code == 403
    assert cliente.get("/profesionales/usuarios-libres", headers=h).status_code == 403
    assert cliente.post("/profesionales", json={"usuario_id": str(libre), **datos(general)}, headers=h).status_code == 403
    assert cliente.put(f"/profesionales/{uuid.uuid4()}", json=datos(general), headers=h).status_code == 403


def test_sin_sesion_recibe_401(cliente):
    assert cliente.get("/profesionales").status_code == 401


# ---------- alta ----------

def test_registrar_con_servicios(cliente, con, mundo, libre, general):
    s1, s2 = un_servicio(con, mundo.clinica_id, general), un_servicio(con, mundo.clinica_id, general)
    r = alta(cliente, mundo, libre, general, [s1, s2])
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["especialidad"] == "General" and p["numero_colegiado"] == "COL-123" and p["activo"] is True
    assert set(p["servicios_ids"]) == {str(s1), str(s2)}


def test_registrar_sin_servicios_y_sin_repetidos(cliente, con, mundo, libre, general):
    s = un_servicio(con, mundo.clinica_id, general)
    assert alta(cliente, mundo, libre, general, [s, s]).json()["servicios_ids"] == [str(s)]
    otro = _usuario(con, "PROFESIONAL", mundo.clinica_id)
    assert alta(cliente, mundo, otro, general).json()["servicios_ids"] == []


def test_usuario_ya_registrado_es_409(cliente, mundo, general):
    assert alta(cliente, mundo, mundo.profesional, general).status_code == 409


@pytest.mark.parametrize("quien", ["recepcion", "admin_otra", "plataforma"])
def test_usuario_sin_rol_de_profesional_o_ajeno_es_422(cliente, mundo, general, quien):
    assert alta(cliente, mundo, getattr(mundo, quien), general).status_code == 422


def test_usuario_dado_de_baja_es_422(cliente, con, mundo, general, libre):
    con.execute("UPDATE usuario SET activo = false WHERE id = %s", (libre,))
    assert alta(cliente, mundo, libre, general).status_code == 422


def test_servicio_de_otra_especialidad_es_422(cliente, con, mundo, libre, general, pediatria):
    ajeno = un_servicio(con, mundo.clinica_id, pediatria)
    assert alta(cliente, mundo, libre, general, [ajeno]).status_code == 422


def test_servicio_o_especialidad_de_otra_clinica_es_422(cliente, con, mundo, libre, general):
    otra = con.execute("SELECT clinica_id FROM usuario WHERE id = %s", (mundo.admin_otra,)).fetchone()["clinica_id"]
    esp_ajena = con.execute("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'Ajena') RETURNING id", (otra,)).fetchone()["id"]
    srv_ajeno = un_servicio(con, otra, esp_ajena)
    assert alta(cliente, mundo, libre, esp_ajena).status_code == 422
    assert alta(cliente, mundo, libre, general, [srv_ajeno]).status_code == 422
    assert alta(cliente, mundo, libre, general, [uuid.uuid4()]).status_code == 422


@pytest.mark.parametrize("cambio", [{"numero_colegiado": "ab"}, {"numero_colegiado": "x" * 21}, {"clinica_id": str(uuid.uuid4())}])
def test_datos_invalidos_son_422(cliente, mundo, libre, general, cambio):
    assert alta(cliente, mundo, libre, general, **cambio).status_code == 422


# ---------- listado ----------

def test_listados(cliente, mundo, libre, general):
    h = como(mundo.admin_clinica)
    assert str(libre) in {u["id"] for u in cliente.get("/profesionales/usuarios-libres", headers=h).json()}
    assert str(mundo.profesional) not in {u["id"] for u in cliente.get("/profesionales/usuarios-libres", headers=h).json()}
    assert alta(cliente, mundo, libre, general).status_code == 201
    assert str(libre) not in {u["id"] for u in cliente.get("/profesionales/usuarios-libres", headers=h).json()}
    nombres = [p["nombre"] for p in cliente.get("/profesionales", headers=h).json()]
    assert len(nombres) == 2  # el de `mundo` y el recién registrado


def test_listado_no_trae_profesionales_de_otra_clinica(cliente, con, mundo, general):
    otra = con.execute("SELECT clinica_id FROM usuario WHERE id = %s", (mundo.admin_otra,)).fetchone()["clinica_id"]
    esp = con.execute("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'X') RETURNING id", (otra,)).fetchone()["id"]
    uid = _usuario(con, "PROFESIONAL", otra)
    ajeno = con.execute("INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s,%s,%s,'C-1') RETURNING id",
                        (otra, uid, esp)).fetchone()["id"]
    assert str(ajeno) not in {p["id"] for p in cliente.get("/profesionales", headers=como(mundo.admin_clinica)).json()}
    assert str(uid) not in {u["id"] for u in cliente.get("/profesionales/usuarios-libres", headers=como(mundo.admin_clinica)).json()}


# ---------- actualización ----------

def test_actualizar_reemplaza_los_servicios(cliente, con, mundo, libre, general):
    h = como(mundo.admin_clinica)
    s1, s2 = un_servicio(con, mundo.clinica_id, general), un_servicio(con, mundo.clinica_id, general)
    p = alta(cliente, mundo, libre, general, [s1]).json()
    r = cliente.put(f"/profesionales/{p['id']}", json=datos(general, [s2], numero_colegiado="COL-999"), headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["servicios_ids"] == [str(s2)] and r.json()["numero_colegiado"] == "COL-999"
    # Lo quitado se deshabilita, no se borra (las citas apuntan a la pareja)...
    fila = con.execute("SELECT activo FROM profesional_servicio WHERE profesional_id = %s AND servicio_id = %s", (p["id"], s1)).fetchone()
    assert fila["activo"] is False
    # ...y se puede volver a habilitar.
    r = cliente.put(f"/profesionales/{p['id']}", json=datos(general, [s1, s2]), headers=h)
    assert set(r.json()["servicios_ids"]) == {str(s1), str(s2)}


def test_quitar_un_servicio_con_citas_no_falla_ni_borra_la_cita(cliente, con, mundo, general):
    """La clave foránea de `cita` apunta a profesional_servicio: por eso se deshabilita en vez de borrar."""
    h = como(mundo.admin_clinica)
    prof = con.execute("SELECT id FROM profesional WHERE usuario_id = %s", (mundo.profesional,)).fetchone()["id"]
    s = un_servicio(con, mundo.clinica_id, general)
    assert cliente.put(f"/profesionales/{prof}", json=datos(general, [s]), headers=h).status_code == 200
    pac = con.execute("INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s,'8-8','P','1990-01-01') RETURNING id",
                      (mundo.clinica_id,)).fetchone()["id"]
    cita = con.execute(
        """INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por)
           VALUES (%s,%s,%s,%s, now() + interval '3 days', now() + interval '3 days 30 minutes', 'RESERVADA', %s) RETURNING id""",
        (mundo.clinica_id, pac, prof, s, mundo.admin_clinica)).fetchone()["id"]
    assert cliente.put(f"/profesionales/{prof}", json=datos(general, []), headers=h).json()["servicios_ids"] == []
    assert con.execute("SELECT estado FROM cita WHERE id = %s", (cita,)).fetchone()["estado"] == "RESERVADA"


def test_cambiar_de_especialidad_exige_servicios_de_la_nueva(cliente, con, mundo, general, pediatria):
    h = como(mundo.admin_clinica)
    prof = con.execute("SELECT id FROM profesional WHERE usuario_id = %s", (mundo.profesional,)).fetchone()["id"]
    s_general = un_servicio(con, mundo.clinica_id, general)
    s_pediatria = un_servicio(con, mundo.clinica_id, pediatria)
    assert cliente.put(f"/profesionales/{prof}", json=datos(pediatria, [s_general]), headers=h).status_code == 422
    r = cliente.put(f"/profesionales/{prof}", json=datos(pediatria, [s_pediatria]), headers=h)
    assert r.status_code == 200 and r.json()["especialidad"] == "Pediatría"


def test_profesional_de_otra_clinica_o_inexistente_responde_404(cliente, con, mundo, general):
    otra = con.execute("SELECT clinica_id FROM usuario WHERE id = %s", (mundo.admin_otra,)).fetchone()["clinica_id"]
    esp = con.execute("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'X') RETURNING id", (otra,)).fetchone()["id"]
    uid = _usuario(con, "PROFESIONAL", otra)
    ajeno = con.execute("INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s,%s,%s,'C-1') RETURNING id",
                        (otra, uid, esp)).fetchone()["id"]
    h = como(mundo.admin_clinica)
    assert cliente.put(f"/profesionales/{ajeno}", json=datos(general), headers=h).status_code == 404
    assert cliente.put(f"/profesionales/{uuid.uuid4()}", json=datos(general), headers=h).status_code == 404
    assert cliente.put("/profesionales/no-es-uuid", json=datos(general), headers=h).status_code == 422
    assert con.execute("SELECT numero_colegiado FROM profesional WHERE id = %s", (ajeno,)).fetchone()["numero_colegiado"] == "C-1"
