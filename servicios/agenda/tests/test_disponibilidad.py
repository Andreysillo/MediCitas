"""RF7 y RF8: espacios disponibles. Se prueba contra la base real, con horarios y citas armados en cada prueba."""

import uuid
from datetime import datetime, timedelta

from conftest import CR, como, proximo


def horario(con, mundo, prof, dia, ini, fin):
    con.execute("INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) VALUES (%s,%s,%s,%s,%s)",
                (mundo.clinica_a, prof, dia, ini, fin))


def espacios(cliente, quien, prof, servicio, dia_iso=1, **extra):
    fecha = proximo(dia_iso, 0).date().isoformat()
    r = cliente.get(f"/profesionales/{prof}/disponibilidad", headers=como(quien),
                    params={"servicio_id": str(servicio), "fecha": fecha, **extra})
    assert r.status_code == 200, r.text
    return [datetime.fromisoformat(e) for e in r.json()["espacios"]]


def horas(lista):
    """Los espacios como 'HH:MM' en hora de Costa Rica, para comparar a simple vista."""
    return [e.astimezone(CR).strftime("%H:%M") for e in lista]


def servicio_de(con, mundo, minutos, nombre):
    esp = con.execute("SELECT especialidad_id FROM servicio WHERE id = %s", (mundo.servicio,)).fetchone()["especialidad_id"]
    sid = con.execute("INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s,%s,%s,%s) RETURNING id",
                      (mundo.clinica_a, nombre, minutos, esp)).fetchone()["id"]
    con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)", (mundo.clinica_a, mundo.prof, sid))
    return sid


def test_sin_horario_no_hay_espacios(cliente, mundo):
    assert espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio) == []


def test_un_inicio_cada_15_minutos_mientras_la_cita_quepa_en_el_bloque(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    lista = espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio)       # servicio de 30 min
    h = horas(lista)
    assert h[0] == "08:00" and h[-1] == "11:30" and len(h) == 15                 # 11:45 + 30 min ya pasa de las 12:00
    # El instante es el correcto: 08:00 en Costa Rica (UTC-6) son las 14:00 UTC.
    assert lista[0] == proximo(1, 8)


def test_la_duracion_del_servicio_decide_cuantos_caben(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "09:00")
    de_60 = servicio_de(con, mundo, 60, "Larga")
    de_90 = servicio_de(con, mundo, 90, "Muy larga")
    assert horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio)) == ["08:00", "08:15", "08:30"]
    assert horas(espacios(cliente, mundo.recepcion, mundo.prof, de_60)) == ["08:00"]
    assert espacios(cliente, mundo.recepcion, mundo.prof, de_90) == []


def test_jornada_partida_el_almuerzo_queda_libre(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    horario(con, mundo, mundo.prof, 1, "13:00", "17:00")
    h = horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))
    assert "11:30" in h and "13:00" in h
    assert not [x for x in h if "11:30" < x < "13:00"]      # ni 11:45 (terminaría 12:15) ni nada de 12:00 a 12:45


def test_una_cita_ocupa_su_espacio_pero_no_el_contiguo(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    mundo.cita(proximo(1, 9))                                # 09:00-09:30
    h = horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))
    assert "08:30" in h                                      # 08:30-09:00 termina justo cuando empieza la cita
    assert not {"08:45", "09:00", "09:15"} & set(h)          # estos sí se traslapan
    assert "09:30" in h                                      # empieza justo cuando termina


def test_solo_las_citas_vigentes_ocupan_espacio(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    mundo.cita(proximo(1, 9), estado="CANCELADA")
    assert "09:00" in horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))
    mundo.cita(proximo(1, 10), estado="ATENDIDA")             # el desenlace no libera el espacio
    assert "10:00" not in horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))


def test_un_bloqueo_retira_la_disponibilidad(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    con.execute("INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo) VALUES (%s,%s,%s,%s,'Permiso')",
                (mundo.clinica_a, mundo.prof, proximo(1, 10), proximo(1, 11)))
    h = horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))
    assert "09:30" in h and "11:00" in h
    assert not [x for x in h if "09:30" < x < "11:00"]


def test_ignorar_cita_libera_el_espacio_de_una_reprogramacion(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    cita = mundo.cita(proximo(1, 9))
    assert "09:00" not in horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio))
    assert "09:00" in horas(espacios(cliente, mundo.recepcion, mundo.prof, mundo.servicio, ignorar_cita=str(cita)))


def test_el_pasado_no_se_ofrece(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    pasado = (proximo(1, 0) - timedelta(days=28)).date().isoformat()                # un lunes ya pasado
    r = cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.recepcion),
                    params={"servicio_id": str(mundo.servicio), "fecha": pasado})
    assert r.json()["espacios"] == []


def test_profesional_o_servicio_que_no_corresponden(cliente, mundo, con):
    horario(con, mundo, mundo.prof2, 1, "08:00", "12:00")
    con.execute("DELETE FROM profesional_servicio WHERE profesional_id = %s", (mundo.prof2,))
    f = {"servicio_id": str(mundo.servicio), "fecha": proximo(1, 0).date().isoformat()}
    quien = como(mundo.recepcion)
    assert cliente.get(f"/profesionales/{mundo.prof2}/disponibilidad", headers=quien, params=f).status_code == 422   # no atiende ese servicio
    assert cliente.get(f"/profesionales/{uuid.uuid4()}/disponibilidad", headers=quien, params=f).status_code == 404
    assert cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=quien, params={**f, "servicio_id": str(uuid.uuid4())}).status_code == 404
    assert cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=quien, params={**f, "fecha": "no-es-fecha"}).status_code == 422


def test_otra_clinica_no_ve_nada_ajeno_I5(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    f = {"servicio_id": str(mundo.servicio), "fecha": proximo(1, 0).date().isoformat()}
    afuera = como(mundo.admin_otra_clinica)
    assert cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=afuera, params=f).status_code == 404
    assert cliente.get(f"/servicios/{mundo.servicio}/disponibilidad", headers=afuera, params={"desde": f["fecha"]}).status_code == 404


def test_permisos_de_consulta(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    for quien in (mundo.admin, mundo.recepcion, mundo.usuario_prof, mundo.usuario_prof2):   # un profesional también puede consultar el de otro
        assert espacios(cliente, quien, mundo.prof, mundo.servicio)
    params = {"servicio_id": str(mundo.servicio), "fecha": proximo(1, 0).date().isoformat()}
    assert cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.plataforma), params=params).status_code == 403
    assert cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", params=params).status_code == 401


def test_rf8_devuelve_solo_los_profesionales_con_espacio_y_todos_los_dias(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "09:00")           # lunes
    horario(con, mundo, mundo.prof, 3, "08:00", "09:00")           # miércoles
    # prof2 atiende el servicio pero no tiene horario: no debe aparecer.
    desde = proximo(1, 0).date()
    r = cliente.get(f"/servicios/{mundo.servicio}/disponibilidad", headers=como(mundo.recepcion), params={"desde": desde.isoformat(), "dias": 7})
    assert r.status_code == 200
    cuerpo = r.json()
    assert [p["profesional"]["nombre"] for p in cuerpo] == ["Dra. Uno"]
    dias = cuerpo[0]["dias"]
    assert [d["fecha"] for d in dias] == [(desde + timedelta(days=i)).isoformat() for i in range(7)]
    assert [len(d["espacios"]) for d in dias] == [3, 0, 3, 0, 0, 0, 0]


def test_rf8_un_servicio_deshabilitado_para_el_profesional_no_lo_incluye(cliente, mundo, con):
    horario(con, mundo, mundo.prof, 1, "08:00", "12:00")
    con.execute("UPDATE profesional_servicio SET activo = false WHERE profesional_id = %s", (mundo.prof,))
    r = cliente.get(f"/servicios/{mundo.servicio}/disponibilidad", headers=como(mundo.recepcion), params={"desde": proximo(1, 0).date().isoformat()})
    assert r.json() == []


def test_rf8_rango_invalido(cliente, mundo):
    desde = proximo(1, 0).date().isoformat()
    for dias in (0, 32, "x"):
        r = cliente.get(f"/servicios/{mundo.servicio}/disponibilidad", headers=como(mundo.recepcion), params={"desde": desde, "dias": dias})
        assert r.status_code == 422, dias
