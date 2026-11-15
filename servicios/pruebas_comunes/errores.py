"""T35: manejo de errores en TODAS las rutas, el mismo barrido para los tres servicios.

RO3 del enunciado: «el servicio no se interrumpe ante una entrada mal formada ni ante un recurso inexistente, sino que
responde con el código que corresponde y permanece operativo». Cada servicio declara en tests/test_aislamiento_i5.py
la solicitud válida de cada ruta (`RUTAS`); este módulo la estropea de cuatro maneras y la manda con cada rol:

  1. RECURSO INEXISTENTE: los mismos ids, pero ninguno existe (el «fantasma» de aislamiento.py). Nunca un 5xx.
  2. IDS MAL FORMADOS: cada uuid (en el camino, la consulta o el cuerpo) cambiado por texto que no lo es. Nunca un éxito
     ni un 5xx: 422 (o 403/404 si el rol ya no entraba por otra razón).
  3. FECHAS MAL FORMADAS: lo mismo con cada fecha.
  4. CUERPO ROTO: JSON truncado, texto, `null`, lista, vacío, campos de otro tipo. Nunca un éxito ni un 5xx.
Toda respuesta de error trae `detalle` (una sola forma para el frontend). Y al final el servicio sigue vivo: /salud responde
y la solicitud válida sigue funcionando para algún rol.
Control: algún rol recibe un 422 por cada estropicio; si no, la ruta podría estar ignorando la entrada y el barrido no probaría nada.
"""

import re
from copy import deepcopy

from aislamiento import _plano, _usuario, construir_clinica, fantasma_de

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")   # una fecha, o fecha y hora (str(datetime) separa con espacio)
CAMINO_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Lo único que puede responder una entrada que no debió aceptarse. 400: el cuerpo ni siquiera es texto (UTF-8 inválido),
# que FastAPI rechaza antes de validar campos; sigue siendo un error del cliente y trae `detalle`.
RECHAZOS = {400, 401, 403, 404, 405, 409, 422}


def _cambiar(valor, patron, reemplazo):
    """Copia de `valor` con cada texto que cumple `patron` cambiado por `reemplazo`. Devuelve (copia, cuántos)."""
    if isinstance(valor, str):
        return (reemplazo, 1) if patron.match(valor) else (valor, 0)
    if isinstance(valor, dict):
        hechos = {k: _cambiar(v, patron, reemplazo) for k, v in valor.items()}
        return {k: v for k, (v, _) in hechos.items()}, sum(n for _, n in hechos.values())
    if isinstance(valor, list):
        hechos = [_cambiar(v, patron, reemplazo) for v in valor]
        return [v for v, _ in hechos], sum(n for _, n in hechos)
    return valor, 0


def _estropear(sol: dict, patron, reemplazo, en_camino=False) -> tuple[dict, int]:
    """La solicitud con cada coincidencia de `patron` cambiada; el segundo valor dice cuántas hubo."""
    nueva, n = deepcopy(sol), 0
    if en_camino:
        nueva["url"], n = CAMINO_UUID.subn(reemplazo, sol["url"])
    for clave in ("params", "json"):
        if sol.get(clave) is not None:
            nueva[clave], hechos = _cambiar(sol[clave], patron, reemplazo)
            n += hechos
    return nueva, n


class Errores:
    def __init__(self, cliente, con, ruta: str, solicitud):
        self.cliente, self.con, self.ruta, self.metodo = cliente, con, ruta, ruta.split(" ", 1)[0]
        self.solicitud = solicitud                  # (w, ref) -> dict(url=, params=, json=)
        self.propia = construir_clinica(con, "propia")
        roles = {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}
        p = self.propia
        self.quienes = {"admin": p.admin, "recepcion": p.recepcion, "profesional": p.usuario_prof,
                        "plataforma": _usuario(con, roles, None, "ADM_PLATAFORMA", "Plataforma")}
        self.fantasma = fantasma_de(p)

    def llamar(self, quien: str, sol: dict, **extra):
        sol = _plano(sol)
        with self.con.transaction(force_rollback=True):
            return self.cliente.request(self.metodo, sol["url"], params=sol.get("params"), json=sol.get("json"),
                                        headers={"X-Usuario-Id": str(self.quienes[quien])}, **extra)

    def _con_todos_los_roles(self, descripcion: str, hacer, permitidos: set[int] | None, esperar_422=True):
        """`hacer(quien)` manda la solicitud. Ningún 5xx, siempre `detalle`, solo códigos de `permitidos` y, si se pide, algún 422."""
        codigos = {}
        for quien in self.quienes:
            r = hacer(quien)
            codigos[quien] = r.status_code
            assert r.status_code < 500, f"{descripcion} ({quien}): {r.status_code} {r.text[:200]}"
            if r.status_code >= 400:
                assert isinstance(r.json(), dict) and "detalle" in r.json(), f"{descripcion} ({quien}): sin «detalle»: {r.text[:200]}"
            if permitidos is not None:
                assert r.status_code in permitidos, f"{descripcion} ({quien}): {r.status_code} {r.text[:200]}"
        if esperar_422:
            assert 422 in codigos.values(), f"{descripcion}: ningún rol recibió 422, ¿la ruta ignora la entrada? {codigos}"

    def correr(self):
        p = self.propia
        valida = self.solicitud(p, p)

        # 1. Recurso inexistente. Cualquier rechazo o incluso un 200 (un listado vacío) es válido; un 5xx no.
        self._con_todos_los_roles("recurso inexistente", lambda q: self.llamar(q, self.solicitud(self.fantasma, self.fantasma)),
                                  permitidos=None, esperar_422=False)

        # 2 y 3. Ids y fechas mal formados.
        for nombre, patron, malo, en_camino in (("id mal formado", UUID, "no-es-un-uuid", True), ("fecha mal formada", FECHA, "31/31/2030", False)):
            roto, cuantos = _estropear(_plano(valida), patron, malo, en_camino)
            if cuantos:
                self._con_todos_los_roles(nombre, lambda q: self.llamar(q, roto), permitidos=RECHAZOS)

        # 4. Cuerpo roto, solo en las rutas que reciben cuerpo.
        if valida.get("json") is not None:
            for descripcion, contenido in {
                "JSON truncado": b'{"campo": ',
                "texto que no es JSON": b"esto no es json",
                "cuerpo vacío": b"",
                "null": b"null",
                "una lista": b"[]",
                "bytes que no son texto": b"\xff\xfe\x00",
            }.items():
                self._con_todos_los_roles(descripcion, lambda q, c=contenido: self._cuerpo(q, valida, c), permitidos=RECHAZOS,
                                          esperar_422=contenido != b"\xff\xfe\x00")      # los bytes inválidos dan 400, ver RECHAZOS
            # Cada campo del cuerpo, uno por uno, de otro tipo: nunca un 5xx.
            for campo in valida["json"]:
                for valor in ({"x": 1}, [1, 2], 12345, True):
                    roto = {**_plano(valida), "json": {**_plano(valida["json"]), campo: valor}}
                    self._con_todos_los_roles(f"campo «{campo}» = {valor!r}", lambda q: self.llamar(q, roto), permitidos=None, esperar_422=False)

        # Y el servicio sigue vivo y atendiendo.
        assert self.cliente.get("/salud").status_code == 200, "el servicio dejó de responder"
        codigos = {q: self.llamar(q, valida).status_code for q in self.quienes}
        assert any(200 <= c < 300 for c in codigos.values()), f"tras los errores, la solicitud válida ya no funciona: {codigos}"

    def _cuerpo(self, quien, sol, contenido: bytes):
        sol = _plano(sol)
        with self.con.transaction(force_rollback=True):
            return self.cliente.request(self.metodo, sol["url"], params=sol.get("params"), content=contenido,
                                        headers={"X-Usuario-Id": str(self.quienes[quien]), "content-type": "application/json"})
