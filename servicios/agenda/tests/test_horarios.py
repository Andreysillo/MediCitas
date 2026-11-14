"""RF5: horario semanal con varios bloques por día."""

import uuid

from conftest import como, proximo


def crear(cliente, quien, prof, dia=1, ini="08:00", fin="12:00"):
    return cliente.post(f"/profesionales/{prof}/horarios", headers=como(quien),
                        json={"dia_semana": dia, "hora_inicio": ini, "hora_fin": fin})


def test_jornada_partida_y_listado_ordenado(cliente, mundo):
    assert crear(cliente, mundo.admin, mundo.prof, ini="13:00", fin="17:00").status_code == 201
    assert crear(cliente, mundo.admin, mundo.prof, ini="08:00", fin="12:00").status_code == 201
    r = cliente.get(f"/profesionales/{mundo.prof}/horarios", headers=como(mundo.admin))
    assert [(h["hora_inicio"], h["hora_fin"]) for h in r.json()] == [("08:00", "12:00"), ("13:00", "17:00")]


def test_bloques_solapados_los_rechaza_el_motor(cliente, mundo):
    crear(cliente, mundo.admin, mundo.prof, ini="08:00", fin="12:00")
    r = crear(cliente, mundo.admin, mundo.prof, ini="11:00", fin="13:00")
    assert r.status_code == 409
    assert r.json()["restriccion"] == "horario_sin_solape"
    assert "solapa" in r.json()["detalle"]
    # Contiguo no es solape: 12:00 es donde termina un bloque y empieza el otro.
    assert crear(cliente, mundo.admin, mundo.prof, ini="12:00", fin="13:00").status_code == 201
    # Otro día, mismas horas: tampoco choca.
    assert crear(cliente, mundo.admin, mundo.prof, dia=2, ini="08:00", fin="12:00").status_code == 201


def test_datos_invalidos_dan_422(cliente, mundo):
    for dia, ini, fin in [(8, "08:00", "12:00"), (0, "08:00", "12:00"), (1, "12:00", "08:00"), (1, "08:00", "08:00"), (1, "8:00", "12:00"), (1, "08:00", "24:00")]:
        assert crear(cliente, mundo.admin, mundo.prof, dia, ini, fin).status_code == 422, (dia, ini, fin)


def test_sin_sesion_o_con_usuario_invalido(cliente, mundo):
    assert cliente.get("/profesionales").status_code == 401
    assert cliente.get("/profesionales", headers={"X-Usuario-Id": "no-es-uuid"}).status_code == 401
    assert cliente.get("/profesionales", headers=como(uuid.uuid4())).status_code == 401
    assert cliente.get("/profesionales", headers=como(mundo.inactivo)).status_code == 403  # baja lógica (RF2)


def test_permisos_por_rol(cliente, mundo):
    # Gestionar el horario: recepción y plataforma no. (Ver la lista de profesionales sí lo puede recepción: abajo.)
    for quien in (mundo.recepcion, mundo.plataforma):
        assert crear(cliente, quien, mundo.prof).status_code == 403
    assert cliente.get("/profesionales", headers=como(mundo.plataforma)).status_code == 403   # no es de ninguna clínica


def test_el_profesional_solo_gestiona_lo_suyo(cliente, mundo):
    assert crear(cliente, mundo.usuario_prof, mundo.prof).status_code == 201
    # Otro profesional de la misma clínica: responde como si no existiera.
    assert crear(cliente, mundo.usuario_prof, mundo.prof2).status_code == 404
    assert cliente.get(f"/profesionales/{mundo.prof2}/horarios", headers=como(mundo.usuario_prof)).status_code == 404


def test_otra_clinica_no_ve_nada_ajeno_I5(cliente, mundo):
    assert crear(cliente, mundo.admin_otra_clinica, mundo.prof).status_code == 404
    assert cliente.get(f"/profesionales/{mundo.prof}/horarios", headers=como(mundo.admin_otra_clinica)).status_code == 404
    assert cliente.get("/profesionales", headers=como(mundo.admin_otra_clinica)).json() == []


def test_profesionales_gestionables(cliente, mundo):
    admin = cliente.get("/profesionales", headers=como(mundo.admin)).json()
    assert {p["nombre"] for p in admin} == {"Dra. Uno", "Dr. Dos"}
    propio = cliente.get("/profesionales", headers=como(mundo.usuario_prof)).json()
    assert [p["nombre"] for p in propio] == ["Dra. Uno"]


def test_recepcion_ve_todos_los_profesionales_para_poder_reservar(cliente, mundo):
    """Recepción reserva (RF9) y necesita el id del profesional; antes recibía 403 y no tenía cómo obtenerlo por la API."""
    r = cliente.get("/profesionales", headers=como(mundo.recepcion))
    assert r.status_code == 200 and {p["nombre"] for p in r.json()} == {"Dra. Uno", "Dr. Dos"}


def test_quitar_un_bloque_lista_las_reservas_que_quedan_fuera_I3(cliente, mundo, con):
    manana = crear(cliente, mundo.admin, mundo.prof, ini="08:00", fin="12:00").json()["id"]
    tarde = crear(cliente, mundo.admin, mundo.prof, ini="13:00", fin="17:00").json()["id"]
    en_tarde = mundo.cita(proximo(1, 14))
    en_manana = mundo.cita(proximo(1, 9))

    r = cliente.delete(f"/horarios/{tarde}", headers=como(mundo.admin))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["conflictos"]] == [str(en_tarde)]  # la de la mañana sigue cubierta
    assert r.json()["conflictos"][0]["paciente"] == "Paciente Uno"

    # No se cancela nada: recepción decide.
    assert con.execute("SELECT estado FROM cita WHERE id = %s", (en_tarde,)).fetchone()["estado"] == "RESERVADA"
    # Quitando también la mañana, quedan fuera las dos.
    r = cliente.delete(f"/horarios/{manana}", headers=como(mundo.admin))
    assert len(r.json()["conflictos"]) == 2


def test_una_cita_que_cruza_dos_bloques_no_esta_cubierta(cliente, mundo):
    """08:00-12:00 y 12:00-13:00 son contiguos, pero una cita de 11:45 a 12:15 no cabe entera en ninguno."""
    crear(cliente, mundo.admin, mundo.prof, ini="08:00", fin="12:00")
    otro = crear(cliente, mundo.admin, mundo.prof, ini="12:00", fin="13:00").json()["id"]
    cita = mundo.cita(proximo(1, 11, 45))
    r = cliente.delete(f"/horarios/{otro}", headers=como(mundo.admin))
    assert [c["id"] for c in r.json()["conflictos"]] == [str(cita)]


def test_quitar_un_horario_inexistente_o_ajeno(cliente, mundo):
    h = crear(cliente, mundo.admin, mundo.prof).json()["id"]
    assert cliente.delete(f"/horarios/{uuid.uuid4()}", headers=como(mundo.admin)).status_code == 404
    assert cliente.delete(f"/horarios/{h}", headers=como(mundo.admin_otra_clinica)).status_code == 404
    assert cliente.delete(f"/horarios/{h}", headers=como(mundo.usuario_prof2)).status_code == 404
