"""RF2: usuarios de la clínica (alta, baja lógica, asignación de rol). Solo el administrador de la clínica; la clínica
sale de la sesión y un usuario de otra clínica no existe para quien consulta (I5)."""

import uuid

import pytest

from conftest import como


def nuevo(**cambios):
    n = uuid.uuid4().hex[:8]
    return {"nombre": "Marta Solano", "rol": "RECEPCION", "usuario": f"marta-{n}", "contrasena": "temporal-123", **cambios}


def ids(r):
    return {u["id"] for u in r.json()}


# ---------- permisos ----------

@pytest.mark.parametrize("quien", ["recepcion", "profesional", "plataforma"])
def test_otros_roles_reciben_403(cliente, mundo, quien):
    h = como(getattr(mundo, quien))
    assert cliente.get("/usuarios", headers=h).status_code == 403
    assert cliente.post("/usuarios", json=nuevo(), headers=h).status_code == 403
    assert cliente.patch(f"/usuarios/{mundo.recepcion}/rol", json={"rol": "PROFESIONAL"}, headers=h).status_code == 403
    assert cliente.patch(f"/usuarios/{mundo.recepcion}/activo", json={"activo": False}, headers=h).status_code == 403


def test_sin_sesion_recibe_401(cliente):
    assert cliente.get("/usuarios").status_code == 401


# ---------- alta ----------

def test_alta_crea_usuario_en_la_clinica_de_la_sesion(cliente, con, mundo, kc):
    r = cliente.post("/usuarios", json=nuevo(), headers=como(mundo.admin_clinica))
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["rol"] == "RECEPCION" and u["activo"] is True and u["es_profesional"] is False
    fila = con.execute("SELECT clinica_id, keycloak_sub FROM usuario WHERE id = %s", (u["id"],)).fetchone()
    assert fila["clinica_id"] == mundo.clinica_id
    assert fila["keycloak_sub"] == kc.creados[0]["sub"]
    assert "temporal-123" not in r.text


def test_alta_no_acepta_clinica_ni_rol_de_plataforma(cliente, mundo, kc):
    h = como(mundo.admin_clinica)
    assert cliente.post("/usuarios", json=nuevo(clinica_id=str(uuid.uuid4())), headers=h).status_code == 422
    assert cliente.post("/usuarios", json=nuevo(rol="ADM_PLATAFORMA"), headers=h).status_code == 422
    assert cliente.post("/usuarios", json=nuevo(contrasena="corta"), headers=h).status_code == 422
    assert kc.creados == []


def test_alta_con_keycloak_caido_no_deja_usuario(cliente, con, mundo, kc):
    kc.falla = "caido"
    datos = nuevo()
    assert cliente.post("/usuarios", json=datos, headers=como(mundo.admin_clinica)).status_code == 503
    assert con.execute("SELECT 1 FROM usuario WHERE nombre = %s AND clinica_id = %s", (datos["nombre"], mundo.clinica_id)).fetchone() is None


# ---------- listado y aislamiento (I5) ----------

def test_listado_solo_trae_la_propia_clinica(cliente, mundo):
    r = cliente.get("/usuarios", headers=como(mundo.admin_clinica))
    assert r.status_code == 200
    propios = {str(mundo.admin_clinica), str(mundo.recepcion), str(mundo.profesional)}
    assert propios <= ids(r)
    assert not ({str(mundo.admin_otra), str(mundo.recepcion_otra), str(mundo.plataforma)} & ids(r))
    yo = [u for u in r.json() if u["yo"]]
    assert [u["id"] for u in yo] == [str(mundo.admin_clinica)]


def test_usuario_de_otra_clinica_responde_404(cliente, con, mundo):
    h = como(mundo.admin_clinica)
    assert cliente.patch(f"/usuarios/{mundo.recepcion_otra}/rol", json={"rol": "PROFESIONAL"}, headers=h).status_code == 404
    assert cliente.patch(f"/usuarios/{mundo.recepcion_otra}/activo", json={"activo": False}, headers=h).status_code == 404
    fila = con.execute("SELECT activo FROM usuario WHERE id = %s", (mundo.recepcion_otra,)).fetchone()
    assert fila["activo"] is True  # no se tocó


def test_usuario_inexistente_responde_404_y_id_mal_formado_422(cliente, mundo):
    h = como(mundo.admin_clinica)
    assert cliente.patch(f"/usuarios/{uuid.uuid4()}/activo", json={"activo": False}, headers=h).status_code == 404
    assert cliente.patch("/usuarios/no-es-uuid/activo", json={"activo": False}, headers=h).status_code == 422


# ---------- rol ----------

def test_cambiar_rol(cliente, con, mundo):
    r = cliente.patch(f"/usuarios/{mundo.recepcion}/rol", json={"rol": "PROFESIONAL"}, headers=como(mundo.admin_clinica))
    assert r.status_code == 200 and r.json()["rol"] == "PROFESIONAL"


def test_no_puede_cambiarse_el_propio_rol(cliente, mundo):
    r = cliente.patch(f"/usuarios/{mundo.admin_clinica}/rol", json={"rol": "RECEPCION"}, headers=como(mundo.admin_clinica))
    assert r.status_code == 409


def test_rol_invalido_es_422(cliente, mundo):
    r = cliente.patch(f"/usuarios/{mundo.recepcion}/rol", json={"rol": "ADM_PLATAFORMA"}, headers=como(mundo.admin_clinica))
    assert r.status_code == 422


def test_profesional_registrado_no_puede_cambiar_de_rol(cliente, mundo):
    r = cliente.patch(f"/usuarios/{mundo.profesional}/rol", json={"rol": "RECEPCION"}, headers=como(mundo.admin_clinica))
    assert r.status_code == 409


def test_se_puede_quitar_un_admin_si_queda_otro(cliente, mundo):
    r = cliente.patch(f"/usuarios/{mundo.segundo_admin}/rol", json={"rol": "RECEPCION"}, headers=como(mundo.admin_clinica))
    assert r.status_code == 200


def test_dos_administradores_no_se_dejan_a_la_clinica_sin_ninguno(cliente, mundo):
    # Quien actúa es siempre un administrador activo distinto del afectado, así que siempre queda al menos uno.
    # (La revisión `_debe_quedar_otro_admin` + el bloqueo de la clínica cubren el caso de dos solicitudes simultáneas.)
    assert cliente.patch(f"/usuarios/{mundo.segundo_admin}/activo", json={"activo": False},
                         headers=como(mundo.admin_clinica)).status_code == 200
    # El segundo ya está dado de baja: no puede responder con otra baja.
    assert cliente.patch(f"/usuarios/{mundo.admin_clinica}/activo", json={"activo": False},
                         headers=como(mundo.segundo_admin)).status_code == 403


# ---------- baja lógica ----------

def test_baja_y_reactivacion(cliente, con, mundo):
    h = como(mundo.admin_clinica)
    r = cliente.patch(f"/usuarios/{mundo.recepcion}/activo", json={"activo": False}, headers=h)
    assert r.status_code == 200 and r.json()["usuario"]["activo"] is False and r.json()["citas_pendientes"] == 0
    assert con.execute("SELECT 1 FROM usuario WHERE id = %s", (mundo.recepcion,)).fetchone()  # no se borra
    # Dado de baja: su siguiente solicitud ya no pasa (sesion.py).
    assert cliente.get("/usuarios", headers=como(mundo.recepcion)).status_code == 403
    r = cliente.patch(f"/usuarios/{mundo.recepcion}/activo", json={"activo": True}, headers=h)
    assert r.json()["usuario"]["activo"] is True


def test_no_puede_darse_de_baja_a_si_mismo(cliente, mundo):
    r = cliente.patch(f"/usuarios/{mundo.admin_clinica}/activo", json={"activo": False}, headers=como(mundo.admin_clinica))
    assert r.status_code == 409


def test_baja_de_profesional_lo_saca_de_la_disponibilidad_y_cuenta_sus_citas(cliente, con, mundo):
    prof = con.execute("SELECT id FROM profesional WHERE usuario_id = %s", (mundo.profesional,)).fetchone()["id"]
    serv = con.execute(
        "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) "
        "SELECT clinica_id, 'Consulta', 30, especialidad_id FROM profesional WHERE id = %s RETURNING id", (prof,)).fetchone()["id"]
    con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s, %s, %s)",
                (mundo.clinica_id, prof, serv))
    pac = con.execute(
        "INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s, '1-1', 'P', '1990-01-01') RETURNING id",
        (mundo.clinica_id,)).fetchone()["id"]
    con.execute(
        """INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por)
           VALUES (%s, %s, %s, %s, now() + interval '2 days', now() + interval '2 days 30 minutes', 'RESERVADA', %s)""",
        (mundo.clinica_id, pac, prof, serv, mundo.admin_clinica))
    r = cliente.patch(f"/usuarios/{mundo.profesional}/activo", json={"activo": False}, headers=como(mundo.admin_clinica))
    assert r.status_code == 200, r.text
    assert r.json()["citas_pendientes"] == 1  # no se cancela: recepción la reprograma
    assert con.execute("SELECT activo FROM profesional WHERE id = %s", (prof,)).fetchone()["activo"] is False
    assert con.execute("SELECT estado FROM cita WHERE profesional_id = %s", (prof,)).fetchone()["estado"] == "RESERVADA"
