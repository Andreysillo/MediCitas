"""RF15 (nota clínica) y RF16 (historial del paciente)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from conftest import _usuario, como


@pytest.fixture
def escenario(con, mundo):
    """Un paciente con una cita (profesional del mundo) y otro profesional con su propia cita, más una cita de otra clínica."""
    c = mundo.clinica_id
    esp = con.execute("SELECT id FROM especialidad WHERE clinica_id = %s", (c,)).fetchone()["id"]
    srv = con.execute("INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, 'Control', 30, %s) RETURNING id",
                      (c, esp)).fetchone()["id"]
    prof = con.execute("SELECT id FROM profesional WHERE usuario_id = %s", (mundo.profesional,)).fetchone()["id"]
    otro_u = _usuario(con, "PROFESIONAL", c)
    otro = con.execute("INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s, %s, %s, 'COL-2') RETURNING id",
                       (c, otro_u, esp)).fetchone()["id"]
    for p in (prof, otro):
        con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s, %s, %s)", (c, p, srv))
    pac = con.execute("INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s, %s, 'Ana', '1990-01-01') RETURNING id",
                      (c, uuid.uuid4().hex[:10])).fetchone()["id"]

    base = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)

    def cita(profesional, estado="ATENDIDA", dias=0, creador=mundo.recepcion):
        ini = base + timedelta(days=dias)
        extra = ("cancelada_por, cancelada_en, motivo_cancelacion", ", %s, now(), 'No puede asistir'") if estado == "CANCELADA" else ("", "")
        cols = "clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por" + (", " + extra[0] if extra[0] else "")
        vals = "%s, %s, %s, %s, %s, %s, %s, %s" + extra[1]
        params = [c, pac, profesional, srv, ini, ini + timedelta(minutes=30), estado, creador] + ([creador] if extra[0] else [])
        return con.execute(f"INSERT INTO cita ({cols}) VALUES ({vals}) RETURNING id", params).fetchone()["id"]

    class E:
        paciente, otro_profesional_usuario = pac, otro_u
        propia = cita(prof, dias=0)
        ajena = cita(otro, dias=1)
        reservada = cita(prof, estado="RESERVADA", dias=2)
        cancelada = cita(prof, estado="CANCELADA", dias=3)

    return E


def nota(cliente, quien, cita, contenido="Paciente estable."):
    return cliente.put(f"/citas/{cita}/nota", json={"contenido": contenido}, headers=como(quien))


def bitacora(con, paciente):
    return [(f["accion"], f["recurso"]) for f in con.execute(
        "SELECT accion, recurso FROM registro_auditoria WHERE paciente_id = %s ORDER BY id", (paciente,)).fetchall()]


# ---------- RF15 ----------

@pytest.mark.parametrize("quien", ["admin_clinica", "recepcion", "plataforma"])
def test_nota_otros_roles_403(cliente, mundo, escenario, quien):
    h = como(getattr(mundo, quien))
    assert nota(cliente, getattr(mundo, quien), escenario.propia).status_code == 403
    assert cliente.get(f"/citas/{escenario.propia}/nota", headers=h).status_code == 403


def test_nota_sin_sesion_401(cliente, escenario):
    assert cliente.put(f"/citas/{escenario.propia}/nota", json={"contenido": "x"}).status_code == 401


def test_profesional_escribe_lee_y_reemplaza_su_nota(cliente, con, mundo, escenario):
    r = nota(cliente, mundo.profesional, escenario.propia)
    assert r.status_code == 200 and r.json()["contenido"] == "Paciente estable."
    r2 = nota(cliente, mundo.profesional, escenario.propia, "  Actualizada ")
    assert r2.json()["contenido"] == "Actualizada" and r2.json()["id"] == r.json()["id"]
    assert cliente.get(f"/citas/{escenario.propia}/nota", headers=como(mundo.profesional)).json()["contenido"] == "Actualizada"
    assert con.execute("SELECT count(*) AS n FROM nota_clinica WHERE cita_id = %s", (escenario.propia,)).fetchone()["n"] == 1


def test_cita_de_otro_profesional_o_clinica_da_404(cliente, mundo, escenario):
    assert nota(cliente, mundo.profesional, escenario.ajena).status_code == 404
    assert cliente.get(f"/citas/{escenario.ajena}/nota", headers=como(mundo.profesional)).status_code == 404
    assert nota(cliente, mundo.profesional, uuid.uuid4()).status_code == 404


def test_solo_citas_atendidas_409(cliente, mundo, escenario):
    assert nota(cliente, mundo.profesional, escenario.reservada).status_code == 409
    assert nota(cliente, mundo.profesional, escenario.cancelada).status_code == 409


@pytest.mark.parametrize("contenido", ["", "   ", "x" * 5001])
def test_nota_invalida_422(cliente, mundo, escenario, contenido):
    assert nota(cliente, mundo.profesional, escenario.propia, contenido).status_code == 422


def test_leer_nota_inexistente_404(cliente, mundo, escenario):
    assert cliente.get(f"/citas/{escenario.propia}/nota", headers=como(mundo.profesional)).status_code == 404


def test_nota_queda_en_la_bitacora(cliente, con, mundo, escenario):
    nota(cliente, mundo.profesional, escenario.propia)
    cliente.get(f"/citas/{escenario.propia}/nota", headers=como(mundo.profesional))
    assert bitacora(con, escenario.paciente) == [("ESCRITURA", "NOTA_CLINICA"), ("LECTURA", "NOTA_CLINICA")]


def test_rechazos_no_dejan_registro(cliente, con, mundo, escenario):
    nota(cliente, mundo.profesional, escenario.reservada)
    nota(cliente, mundo.profesional, escenario.ajena)
    assert bitacora(con, escenario.paciente) == []


# ---------- RF16 ----------

@pytest.mark.parametrize("quien", ["admin_clinica", "recepcion", "profesional"])
def test_historial_lo_ven_estos_roles(cliente, mundo, escenario, quien):
    r = cliente.get(f"/pacientes/{escenario.paciente}/historial", headers=como(getattr(mundo, quien)))
    assert r.status_code == 200


def test_historial_plataforma_403_y_sin_sesion_401(cliente, mundo, escenario):
    assert cliente.get(f"/pacientes/{escenario.paciente}/historial", headers=como(mundo.plataforma)).status_code == 403
    assert cliente.get(f"/pacientes/{escenario.paciente}/historial").status_code == 401


def test_historial_trae_todas_las_citas_con_estado_de_la_mas_reciente_a_la_mas_antigua(cliente, mundo, escenario):
    h = cliente.get(f"/pacientes/{escenario.paciente}/historial", headers=como(mundo.recepcion)).json()
    assert [x["id"] for x in h] == [str(escenario.cancelada), str(escenario.reservada), str(escenario.ajena), str(escenario.propia)]
    assert [x["estado"] for x in h] == ["CANCELADA", "RESERVADA", "ATENDIDA", "ATENDIDA"]
    assert h[0]["motivo_cancelacion"] == "No puede asistir" and h[0]["servicio"] == "Control"
    assert "contenido" not in h[3]


def test_historial_de_otra_clinica_404(cliente, mundo, escenario):
    assert cliente.get(f"/pacientes/{escenario.paciente}/historial", headers=como(mundo.recepcion_otra)).status_code == 404
    assert cliente.get(f"/pacientes/{uuid.uuid4()}/historial", headers=como(mundo.recepcion)).status_code == 404
