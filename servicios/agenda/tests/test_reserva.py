"""RF9: reservar una cita. Cada prueba se deshace con ROLLBACK."""

import uuid
from datetime import datetime, timedelta

from conftest import como, poner_horario, proximo


def reservar(cliente, quien, mundo, inicio, paciente=None, profesional=None, servicio=None, **extra):
    return cliente.post("/citas", headers=como(quien), json={
        "paciente_id": str(paciente or mundo.paciente), "profesional_id": str(profesional or mundo.prof),
        "servicio_id": str(servicio or mundo.servicio), "inicio": inicio.isoformat(), **extra})


def con_horario(con, mundo, prof=None):
    """Lunes de 08:00 a 12:00 y de 13:00 a 17:00 (jornada partida)."""
    poner_horario(con, mundo, prof or mundo.prof, 1, "08:00", "12:00")
    poner_horario(con, mundo, prof or mundo.prof, 1, "13:00", "17:00")


def test_reserva_concedida(cliente, mundo, con):
    con_horario(con, mundo)
    r = reservar(cliente, mundo.recepcion, mundo, proximo(1, 9))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["estado"] == "RESERVADA" and c["paciente"] == "Paciente Uno" and c["servicio"] == "Consulta"
    assert c["creada_por"] == str(mundo.recepcion)
    fila = con.execute("SELECT clinica_id, inicio, fin FROM cita WHERE id = %s", (c["id"],)).fetchone()
    assert fila["clinica_id"] == mundo.clinica_a
    assert fila["fin"] - fila["inicio"] == timedelta(minutes=30)        # I4: la duración la puso el servicio


def test_la_duracion_la_decide_el_servicio_y_no_se_puede_enviar_fin_ni_clinica(cliente, mundo, con):
    con_horario(con, mundo)
    esp = con.execute("SELECT especialidad_id FROM servicio WHERE id = %s", (mundo.servicio,)).fetchone()["especialidad_id"]
    largo = con.execute("INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s,'Larga',45,%s) RETURNING id",
                        (mundo.clinica_a, esp)).fetchone()["id"]
    con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)", (mundo.clinica_a, mundo.prof, largo))
    c = reservar(cliente, mundo.recepcion, mundo, proximo(1, 9), servicio=largo).json()
    assert datetime.fromisoformat(c["fin"]) - datetime.fromisoformat(c["inicio"]) == timedelta(minutes=45)

    # Intentos de enviar el fin (I4) o la clínica (I5) por la cuenta del cliente en la solicitud: se rechazan, no se ignoran en silencio.
    fin_falso = (proximo(1, 11)).isoformat()
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 10), fin=fin_falso).status_code == 422
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 10), clinica_id=str(mundo.clinica_b)).status_code == 422


def test_solape_de_profesional_lo_rechaza_el_motor(cliente, mundo, con):
    con_horario(con, mundo)
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9)).status_code == 201
    otro = mundo.nuevo_paciente()
    for minuto in (0, 15):                                                    # mismo espacio y solape parcial
        r = reservar(cliente, mundo.recepcion, mundo, proximo(1, 9, minuto), paciente=otro)
        assert r.status_code == 409 and r.json()["restriccion"] == "cita_sin_solape_profesional"
        assert r.json()["detalle"] == "Ese espacio ya fue tomado"
    # Contiguo no es solape.
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9, 30), paciente=otro).status_code == 201
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 8, 30), paciente=otro).status_code == 201


def test_solape_de_paciente_con_otro_profesional(cliente, mundo, con):
    con_horario(con, mundo)
    con_horario(con, mundo, mundo.prof2)
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9)).status_code == 201
    r = reservar(cliente, mundo.recepcion, mundo, proximo(1, 9), profesional=mundo.prof2)
    assert r.status_code == 409 and r.json()["restriccion"] == "cita_sin_solape_paciente"


def test_cancelar_libera_el_espacio_I7(cliente, mundo, con):
    con_horario(con, mundo)
    mundo.cita(proximo(1, 9), estado="CANCELADA")
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9)).status_code == 201


def test_fuera_del_horario_I3(cliente, mundo, con):
    con_horario(con, mundo)
    casos = {
        "antes de abrir": proximo(1, 7, 30),
        "termina después de cerrar el bloque": proximo(1, 11, 45),       # 11:45-12:15
        "en el almuerzo": proximo(1, 12, 15),
        "cruza el almuerzo": proximo(1, 12, 45),                         # 12:45-13:15
        "día sin horario": proximo(2, 9),
        "pasada la tarde": proximo(1, 17, 0),
    }
    for nombre, inicio in casos.items():
        r = reservar(cliente, mundo.recepcion, mundo, inicio)
        assert r.status_code == 422 and "fuera de la atención" in r.json()["detalle"], nombre
    # Justo en los bordes sí cabe.
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 11, 30)).status_code == 201     # termina a las 12:00
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 13, 0), paciente=mundo.nuevo_paciente()).status_code == 201


def test_bloqueo_I3(cliente, mundo, con):
    con_horario(con, mundo)
    con.execute("INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo) VALUES (%s,%s,%s,%s,'Permiso')",
                (mundo.clinica_a, mundo.prof, proximo(1, 10), proximo(1, 11)))
    r = reservar(cliente, mundo.recepcion, mundo, proximo(1, 10, 15))
    assert r.status_code == 422 and "bloqueo" in r.json()["detalle"]
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9, 30)).status_code == 201     # termina justo al empezar el bloqueo
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 11), paciente=mundo.nuevo_paciente()).status_code == 201


def test_no_se_reserva_en_el_pasado(cliente, mundo, con):
    con_horario(con, mundo)
    r = reservar(cliente, mundo.recepcion, mundo, proximo(1, 9) - timedelta(days=28))
    assert r.status_code == 422 and "pasado" in r.json()["detalle"]


def test_referencias_invalidas_responden_igual_que_las_ajenas_I5(cliente, mundo, con):
    con_horario(con, mundo)
    inicio = proximo(1, 9)
    mensaje = "no existen en esta clínica"
    # Ids inexistentes y de otra clínica dan la misma respuesta: no se revela que existen.
    otra = como(mundo.admin_otra_clinica)
    assert mensaje in reservar(cliente, mundo.admin_otra_clinica, mundo, inicio).json()["detalle"]
    for campo in ("paciente", "profesional", "servicio"):
        r = reservar(cliente, mundo.recepcion, mundo, inicio, **{campo: uuid.uuid4()})
        assert r.status_code == 422 and mensaje in r.json()["detalle"], campo


def test_profesional_o_servicio_no_disponibles(cliente, mundo, con):
    con_horario(con, mundo)
    inicio = proximo(1, 9)
    con.execute("UPDATE profesional_servicio SET activo = false WHERE profesional_id = %s", (mundo.prof,))
    assert "no atiende" in reservar(cliente, mundo.recepcion, mundo, inicio).json()["detalle"]
    con.execute("UPDATE profesional_servicio SET activo = true WHERE profesional_id = %s", (mundo.prof,))
    con.execute("UPDATE servicio SET activo = false WHERE id = %s", (mundo.servicio,))
    assert "desactivado" in reservar(cliente, mundo.recepcion, mundo, inicio).json()["detalle"]
    con.execute("UPDATE servicio SET activo = true WHERE id = %s", (mundo.servicio,))
    con.execute("UPDATE profesional SET activo = false WHERE id = %s", (mundo.prof,))
    assert "no está activo" in reservar(cliente, mundo.recepcion, mundo, inicio).json()["detalle"]


def test_permisos(cliente, mundo, con):
    con_horario(con, mundo)
    inicio = proximo(1, 9)
    for quien in (mundo.usuario_prof, mundo.plataforma):
        assert reservar(cliente, quien, mundo, inicio).status_code == 403
    assert cliente.post("/citas", json={}).status_code == 401
    assert reservar(cliente, mundo.admin, mundo, inicio).status_code == 201           # el administrador de clínica también agenda


def test_solicitudes_mal_formadas(cliente, mundo):
    base = {"paciente_id": str(mundo.paciente), "profesional_id": str(mundo.prof), "servicio_id": str(mundo.servicio)}
    for inicio in ("2030-01-01T09:00:00", "2030-01-01T09:00:30-06:00", "no-es-fecha", None):   # sin zona, con segundos, basura, ausente
        cuerpo = {**base, **({"inicio": inicio} if inicio else {})}
        assert cliente.post("/citas", headers=como(mundo.recepcion), json=cuerpo).status_code == 422, inicio
    assert cliente.post("/citas", headers=como(mundo.recepcion), json={**base, "inicio": "2030-01-01T09:00:00-06:00", "paciente_id": "x"}).status_code == 422


def test_la_reserva_desaparece_de_la_disponibilidad_I7(cliente, mundo, con):
    con_horario(con, mundo)
    params = {"servicio_id": str(mundo.servicio), "fecha": proximo(1, 0).date().isoformat()}
    antes = cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.recepcion), params=params).json()["espacios"]
    assert reservar(cliente, mundo.recepcion, mundo, proximo(1, 9)).status_code == 201
    despues = cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.recepcion), params=params).json()["espacios"]
    assert len(antes) - len(despues) == 3                         # 08:45, 09:00 y 09:15 dejaron de estar libres


def test_valores_extremos_no_tumban_el_servicio(cliente, mundo, con):
    """Requisito de operación 3: una entrada absurda responde 422, nunca 500."""
    con_horario(con, mundo)
    quien = como(mundo.recepcion)
    base = {"paciente_id": str(mundo.paciente), "profesional_id": str(mundo.prof), "servicio_id": str(mundo.servicio)}

    # Sumarle la duración se sale del calendario de Python.
    assert cliente.post("/citas", headers=quien, json={**base, "inicio": "9999-12-31T23:59:00+00:00"}).status_code == 422
    r = cliente.get(f"/servicios/{mundo.servicio}/disponibilidad", headers=quien, params={"desde": "9999-12-25", "dias": 31})
    assert r.status_code == 422
    r = cliente.post(f"/profesionales/{mundo.prof}/bloqueos", headers=como(mundo.admin),
                     json={"inicio": "9999-12-31T22:00:00+00:00", "fin": "9999-12-31T23:00:00-14:00", "motivo": "Prueba"})
    assert r.status_code == 422

    # PostgreSQL no admite el carácter NUL en un texto.
    cita = mundo.cita(proximo(1, 9))
    r = cliente.post(f"/citas/{cita}/cancelar", headers=quien, json={"motivo": "abc\u0000def"})
    assert r.status_code == 422

    assert cliente.get("/salud").status_code == 200
