"""T26: barrido de intentos de fuga entre clínicas (I5), el mismo para los tres servicios.

I5: «Ningún dato de una clínica resulta accesible desde otra, por ninguna ruta ni combinación de parámetros».
Cada servicio declara en su tests/test_aislamiento_i5.py una tabla con TODAS sus rutas; este módulo las ataca.
El Dockerfile (etapa `pruebas`) lo copia junto a las pruebas de cada servicio, así no hay tres copias. Vive fuera de
`comun/` a propósito: allí se instalaría como paquete en la imagen de producción.

El mundo: dos clínicas armadas igual. La VÍCTIMA lleva en cada texto un canario (una palabra única) y la PROPIA
es la del atacante. Además un FANTASMA: la víctima con todos sus ids cambiados por ids que no existen.

Por cada ruta y cada atacante (administrador, recepción y profesional de la clínica propia, y el administrador de
plataforma) se comprueba:
  1. Ids ajenos (en la ruta, en la consulta o en el cuerpo, solos o mezclados con ids propios) responden EXACTAMENTE
     lo mismo que ids inventados: mismo código y mismo mensaje. Si no, la respuesta revelaría que el dato existe.
  2. Ninguna respuesta contiene el canario ni un id de la víctima que el atacante no haya enviado él mismo.
  3. Inyectar la clínica víctima (`clinica_id` en la consulta y en el cuerpo, cabecera X-Clinica-Id) no cambia nada.
  4. Los datos de la víctima quedan idénticos: la huella de cada tabla con `clinica_id` no cambia.
  5. No interferencia: lo que cada atacante ve con sus propios datos es idéntico antes y después de que la víctima
     exista. Atrapa la fuga que no trae ni un id ni un texto ajeno, como un conteo que suma citas de otra clínica.
  6. Control: la misma solicitud con los ids propios SÍ funciona para algún atacante. Sin esto, una ruta rota (que
     a todos responde 404) pasaría las comprobaciones de arriba sin demostrar nada.
Cada intento corre en un punto de guardado que se deshace al terminar: todos ven el mundo intacto y el orden no importa.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

CR = timezone(timedelta(hours=-6))          # las dos clínicas son de Costa Rica: UTC-6 todo el año
CANARIO = "FUGA" + uuid.uuid4().hex[:8]     # si aparece en una respuesta al atacante, hubo fuga
_UNICO = re.compile(r"u[0-9a-f]{12}")
FUERA_DEL_BARRIDO = {"/salud", "/listo", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}  # sin datos de nadie


def unico() -> str:
    """Un texto distinto en cada llamada (identificaciones, nombres de usuario): así crear dos veces nunca choca."""
    return "u" + uuid.uuid4().hex[:12]


def _usuario(con, roles, clinica, rol, nombre):
    uid = uuid.uuid4()
    con.execute("INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre) VALUES (%s,%s,%s,%s,%s)",
                (uid, clinica, roles[rol], str(uid), nombre))
    return uid


def construir_clinica(con, canario: str) -> SimpleNamespace:
    """Una clínica con un poco de todo: un usuario por rol, catálogo, paciente, un registro de bitácora y DOS
    profesionales, cada uno con horario, bloqueo, una cita futura, una pasada sin desenlace y una atendida con su nota.
    Los del segundo terminan en `_colega`: con ellos se prueba el «solo los propios» de la matriz (T29). `canario` va en
    cada texto."""
    def ins(sql, *p):
        return con.execute(sql + " RETURNING id", p).fetchone()["id"]

    roles = {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}
    w = SimpleNamespace()
    # El nombre de la clínica NO lleva canario: el administrador de plataforma ve la lista de clínicas por diseño (RF1).
    w.clinica = ins("INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES ('Clínica', %s, 'America/Costa_Rica')", unico())
    w.admin = _usuario(con, roles, w.clinica, "ADM_CLINICA", f"Admin {canario}")
    w.recepcion = _usuario(con, roles, w.clinica, "RECEPCION", f"Recepción {canario}")
    w.usuario_libre = _usuario(con, roles, w.clinica, "PROFESIONAL", f"Dr. libre {canario}")   # aún sin registrar (RF4)

    w.especialidad = ins("INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, %s)", w.clinica, f"Esp {canario}")
    w.servicio = ins("INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s,%s,30,%s)",
                     w.clinica, f"Serv {canario}", w.especialidad)
    w.identificacion = f"{canario}{unico()}"      # para buscar al paciente por texto, no solo por id
    w.paciente = ins("""INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento, telefono, correo)
                        VALUES (%s,%s,%s,'1990-01-01',%s,%s)""", w.clinica, w.identificacion, f"Paciente {canario}", canario, f"{canario}@correo.cr")

    # Todo lo futuro pasa en un mismo día: atienden de 08:00 a 12:00 y queda libre el espacio de las 09:00.
    w.fecha = (datetime.now(CR) + timedelta(days=8)).date()
    ayer = datetime.now(CR).date() - timedelta(days=1)
    dia = lambda d, h: datetime(d.year, d.month, d.day, h, tzinfo=CR)
    w.inicio_libre = dia(w.fecha, 9)

    def profesional(sufijo, nombre, h_cita, h_bloqueo, h_pasada):
        """Registra un profesional con su agenda y deja sus ids en w con el sufijo dado. El paciente es el mismo para los
        dos, así que las horas de sus citas no se cruzan (I2)."""
        usuario = _usuario(con, roles, w.clinica, "PROFESIONAL", f"{nombre} {canario}")
        prof = ins("INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s,%s,%s,%s)",
                   w.clinica, usuario, w.especialidad, f"C{canario}")
        con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)", (w.clinica, prof, w.servicio))
        horarios = [ins("INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) VALUES (%s,%s,%s,'08:00','12:00')",
                        w.clinica, prof, d) for d in range(1, 8)]
        bloqueo = ins("INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo) VALUES (%s,%s,%s,%s,%s)",
                      w.clinica, prof, dia(w.fecha, h_bloqueo), dia(w.fecha, h_bloqueo) + timedelta(minutes=30), f"Motivo {canario}")

        def cita(inicio, estado="RESERVADA"):
            return ins("""INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                       w.clinica, w.paciente, prof, w.servicio, inicio, inicio + timedelta(minutes=30), estado, w.admin)
        atendida = cita(dia(ayer, h_pasada + 1), "ATENDIDA")          # la nota solo va en una atendida (RF15)
        valores = dict(usuario_prof=usuario, prof=prof, horario=horarios[0], bloqueo=bloqueo, cita=cita(dia(w.fecha, h_cita)),
                       cita_pasada=cita(dia(ayer, h_pasada)),          # aún sin desenlace (RF12)
                       cita_atendida=atendida,
                       nota=ins("INSERT INTO nota_clinica (clinica_id, cita_id, contenido) VALUES (%s,%s,%s)", w.clinica, atendida, f"Nota {canario}"))
        for k, v in valores.items():
            setattr(w, k + sufijo, v)

    profesional("", "Dra.", h_cita=8, h_bloqueo=10, h_pasada=8)
    profesional("_colega", "Dr. colega", h_cita=11, h_bloqueo=10, h_pasada=10)
    con.execute("INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso) VALUES (%s,%s,%s,'LECTURA','NOTA_CLINICA')",
                (w.clinica, w.admin, w.paciente))
    return w


def fantasma_de(w: SimpleNamespace) -> SimpleNamespace:
    """La misma clínica con todos sus ids cambiados por ids que no existen en ninguna parte."""
    return SimpleNamespace(**{k: uuid.uuid4() if isinstance(v, UUID) else v for k, v in vars(w).items()})


def _ids(w) -> dict[str, str]:
    return {str(v): k for k, v in vars(w).items() if isinstance(v, UUID)}


def huella(con, clinica) -> dict[str, str]:
    """Un md5 por tabla de todas las filas de esa clínica. Las tablas se descubren solas: una tabla nueva con
    `clinica_id` queda vigilada sin tocar este archivo."""
    tablas = [f["relname"] for f in con.execute(
        """SELECT c.relname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE a.attname = 'clinica_id' AND c.relkind = 'r' AND n.nspname = 'public' ORDER BY 1""")]
    h = {"clinica": con.execute("SELECT md5(t::text) AS h FROM clinica t WHERE id = %s", (clinica,)).fetchone()["h"]}
    for t in tablas:   # el nombre sale del catálogo, no del usuario: no hay inyección posible
        h[t] = con.execute(f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) AS h FROM {t} t WHERE clinica_id = %s",
                           (clinica,)).fetchone()["h"]
    return h


def _rutas(routes, prefijo=""):
    """(camino, métodos) de cada ruta, entrando a los routers incluidos (FastAPI 0.16x los guarda como `_IncludedRouter`)."""
    for r in routes:
        if hasattr(r, "original_router"):
            yield from _rutas(r.original_router.routes, prefijo + r.include_context.prefix)
        elif hasattr(r, "methods"):
            yield prefijo + r.path, r.methods


def comprobar_cobertura(app, rutas: dict) -> None:
    """Toda ruta del servicio está en la tabla del barrido: si alguien agrega una y no la declara, esto falla."""
    declaradas = set(rutas)
    reales = {f"{m} {camino}" for camino, metodos in _rutas(app.routes) if camino not in FUERA_DEL_BARRIDO for m in metodos if m != "HEAD"}
    assert reales == declaradas, f"sin barrido: {sorted(reales - declaradas)}; ya no existen: {sorted(declaradas - reales)}"


def _plano(x):
    """UUID, fechas y demás a texto, como viajarían en JSON."""
    return json.loads(json.dumps(x, default=str))


class Barrido:
    def __init__(self, cliente, con, ruta: str, solicitud):
        self.cliente, self.con, self.ruta, self.metodo = cliente, con, ruta, ruta.split(" ", 1)[0]
        self.solicitud = solicitud              # (w, ref) -> dict(url=, params=, json=): w = lo que se toca, ref = lo que se menciona
        self.propia = construir_clinica(con, "propia")
        plataforma = _usuario(con, {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}, None, "ADM_PLATAFORMA", "Plataforma")
        p = self.propia
        self.atacantes = {"admin": p.admin, "recepcion": p.recepcion, "profesional": p.usuario_prof, "plataforma": plataforma}
        # Lo que cada uno ve ANTES de que la víctima exista (solo lecturas: una escritura no "ve" nada ajeno).
        self.huella_victima = None
        self.antes = {q: self._lectura_propia(q) for q in self.atacantes} if self.metodo == "GET" else {}
        self.victima = construir_clinica(con, CANARIO)
        self.fantasma = fantasma_de(self.victima)
        self.huella_victima = huella(con, self.victima.clinica)

    def llamar(self, quien: str, sol: dict, cabeceras: dict | None = None):
        """La solicitud dentro de un punto de guardado que se deshace siempre; antes de deshacerlo, la huella de la víctima."""
        sol = _plano(sol)
        with self.con.transaction(force_rollback=True):
            r = self.cliente.request(self.metodo, sol["url"], params=sol.get("params"), json=sol.get("json"),
                                     headers={"X-Usuario-Id": str(self.atacantes[quien]), **(cabeceras or {})})
            if self.huella_victima is not None:
                assert huella(self.con, self.victima.clinica) == self.huella_victima, f"{quien}: cambió datos de la víctima con {sol}"
        return r, json.dumps(sol)

    def sin_fuga(self, quien, r, enviado):
        """Ni el canario ni un id de la víctima que el atacante no haya mandado (un 422 repite lo que recibió)."""
        assert CANARIO not in r.text, f"{quien}: la respuesta trae datos de la víctima: {r.text[:300]}"
        ids = _ids(self.victima)
        if quien == "plataforma":
            ids.pop(str(self.victima.clinica))   # el administrador de plataforma lista las clínicas (RF1)
        filtrados = [n for i, n in ids.items() if i in r.text and i not in enviado]
        assert not filtrados, f"{quien}: la respuesta trae ids de la víctima ({filtrados}): {r.text[:300]}"

    def _normal(self, texto, w):
        for i, nombre in _ids(w).items():
            texto = texto.replace(i, f"<{nombre}>")
        return _UNICO.sub("<unico>", texto)

    def _lectura_propia(self, quien):
        r, _ = self.llamar(quien, self.solicitud(self.propia, self.propia))
        return r.status_code, r.text

    def correr(self):
        v, p, f = self.victima, self.propia, self.fantasma
        # Qué mezclas tienen sentido: si la ruta no usa ids en el camino (o en la consulta/cuerpo), esa mezcla repite otra.
        menciona = CANARIO in json.dumps(_plano(self.solicitud(p, v))) or any(i in json.dumps(_plano(self.solicitud(p, v))) for i in _ids(v))
        toca = any(i in json.dumps(_plano(self.solicitud(v, p))) for i in _ids(v))
        intentos = [((v, v), (f, f))] + ([((p, v), (p, f))] if menciona else []) + ([((v, p), (f, p))] if toca else [])

        for quien in self.atacantes:
            for ataque, testigo in intentos:
                r, enviado = self.llamar(quien, self.solicitud(*ataque))
                t, _ = self.llamar(quien, self.solicitud(*testigo))
                self.sin_fuga(quien, r, enviado)
                assert r.status_code == t.status_code, f"{quien}: ajeno {r.status_code} {r.text[:200]} / inexistente {t.status_code} {t.text[:200]}"
                if r.status_code >= 400:   # y el mismo mensaje: un texto distinto también delata que el dato existe
                    assert self._normal(r.text, v) == self._normal(t.text, f), f"{quien}: {r.text[:200]} / {t.text[:200]}"

            # Inyección de la clínica víctima en todo lo que el cliente controla, sobre una solicitud propia válida.
            limpia = self.solicitud(p, p)
            inyectada = {**limpia, "params": {**(limpia.get("params") or {}), "clinica_id": v.clinica}}
            if isinstance(limpia.get("json"), dict):
                inyectada["json"] = {**limpia["json"], "clinica_id": v.clinica}
            r, enviado = self.llamar(quien, inyectada, {"X-Clinica-Id": str(v.clinica)})
            self.sin_fuga(quien, r, enviado)
            if self.metodo == "GET":   # sin cuerpo, la inyección se ignora: la respuesta es la misma que sin ella
                assert r.status_code == self.llamar(quien, limpia)[0].status_code, f"{quien}: la inyección cambió la respuesta"
            else:                      # con cuerpo, el esquema rechaza el campo que no existe o lo ignora; nunca un 5xx
                assert r.status_code < 500, f"{quien}: {r.status_code} {r.text[:200]}"

        # No interferencia. Única excepción: el administrador de plataforma lista las clínicas (RF1), y la víctima es una más.
        for quien, antes in self.antes.items():
            if not (quien == "plataforma" and self.ruta == "GET /clinicas"):
                assert self._lectura_propia(quien) == antes, f"{quien}: lo que ve de su propia clínica cambió al existir otra"

        # Control: con los ids propios, la ruta sí sirve para alguien. Así los 404 de arriba son por la clínica.
        codigos = {quien: self.llamar(quien, self.solicitud(p, p))[0].status_code for quien in self.atacantes}
        assert any(200 <= c < 300 for c in codigos.values()), f"ningún rol pudo usar la ruta con sus propios datos: {codigos}"
