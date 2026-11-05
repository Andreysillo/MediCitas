"""RF6: bloqueos de agenda. Un bloqueo no cancela citas: las que caen dentro se listan como conflicto."""

import uuid
from datetime import timedelta

from conftest import como, proximo


def bloquear(cliente, quien, prof, inicio, fin, motivo="Vacaciones"):
    return cliente.post(f"/profesionales/{prof}/bloqueos", headers=como(quien),
                        json={"inicio": inicio.isoformat(), "fin": fin.isoformat(), "motivo": motivo})


def test_el_bloqueo_lista_los_conflictos_y_no_cancela_nada(cliente, mundo, con):
    dentro = mundo.cita(proximo(1, 10))
    mundo.cita(proximo(1, 14))                                  # otro rato del día: no choca
    mundo.cita(proximo(1, 10), estado="CANCELADA")              # ya no ocupa espacio
    mundo.cita(proximo(1, 11), estado="ATENDIDA")               # ni las que ya tienen desenlace

    r = bloquear(cliente, mundo.admin, mundo.prof, proximo(1, 9), proximo(1, 12))
    assert r.status_code == 201
    assert [c["id"] for c in r.json()["conflictos"]] == [str(dentro)]

    assert con.execute("SELECT estado FROM cita WHERE id = %s", (dentro,)).fetchone()["estado"] == "RESERVADA"
    listado = cliente.get(f"/profesionales/{mundo.prof}/bloqueos", headers=como(mundo.admin)).json()
    assert [len(b["conflictos"]) for b in listado] == [1]


def test_una_cita_que_termina_justo_cuando_empieza_el_bloqueo_no_choca(cliente, mundo):
    mundo.cita(proximo(1, 8, 30))        # 08:30-09:00
    mundo.cita(proximo(1, 12))           # 12:00-12:30
    r = bloquear(cliente, mundo.admin, mundo.prof, proximo(1, 9), proximo(1, 12))
    assert r.json()["conflictos"] == []


def test_los_conflictos_son_solo_de_ese_profesional(cliente, mundo):
    mundo.cita(proximo(1, 10), profesional=mundo.prof2)
    assert bloquear(cliente, mundo.admin, mundo.prof, proximo(1, 9), proximo(1, 12)).json()["conflictos"] == []


def test_datos_invalidos(cliente, mundo):
    ini = proximo(1, 9)
    assert bloquear(cliente, mundo.admin, mundo.prof, ini, ini).status_code == 422                  # fin = inicio
    assert bloquear(cliente, mundo.admin, mundo.prof, ini, ini + timedelta(hours=1), "ab").status_code == 422
    assert bloquear(cliente, mundo.admin, mundo.prof, ini, ini + timedelta(hours=1), "x" * 201).status_code == 422
    r = cliente.post(f"/profesionales/{mundo.prof}/bloqueos", headers=como(mundo.admin),
                     json={"inicio": "2030-01-01T09:00:00", "fin": "2030-01-01T10:00:00", "motivo": "sin zona"})
    assert r.status_code == 422                                                                     # instante sin zona horaria


def test_un_bloqueo_que_ya_termino_no_tiene_efecto(cliente, mundo):
    ayer = proximo(1, 9) - timedelta(days=30)
    r = bloquear(cliente, mundo.admin, mundo.prof, ayer, ayer + timedelta(hours=2))
    assert r.status_code == 422 and "ya terminó" in r.json()["detalle"]


def test_eliminar_bloqueo(cliente, mundo):
    b = bloquear(cliente, mundo.admin, mundo.prof, proximo(1, 9), proximo(1, 12)).json()["id"]
    assert cliente.delete(f"/bloqueos/{b}", headers=como(mundo.admin)).status_code == 204
    assert cliente.get(f"/profesionales/{mundo.prof}/bloqueos", headers=como(mundo.admin)).json() == []
    assert cliente.delete(f"/bloqueos/{b}", headers=como(mundo.admin)).status_code == 404
    assert cliente.delete(f"/bloqueos/{uuid.uuid4()}", headers=como(mundo.admin)).status_code == 404


def test_permisos(cliente, mundo):
    ini, fin = proximo(1, 9), proximo(1, 12)
    assert bloquear(cliente, mundo.recepcion, mundo.prof, ini, fin).status_code == 403
    assert bloquear(cliente, mundo.plataforma, mundo.prof, ini, fin).status_code == 403
    assert bloquear(cliente, mundo.admin_otra_clinica, mundo.prof, ini, fin).status_code == 404   # I5
    assert bloquear(cliente, mundo.usuario_prof2, mundo.prof, ini, fin).status_code == 404        # lo de otro profesional
    propio = bloquear(cliente, mundo.usuario_prof, mundo.prof, ini, fin)
    assert propio.status_code == 201
    assert cliente.delete(f"/bloqueos/{propio.json()['id']}", headers=como(mundo.usuario_prof2)).status_code == 404
    assert cliente.delete(f"/bloqueos/{propio.json()['id']}", headers=como(mundo.admin_otra_clinica)).status_code == 404
