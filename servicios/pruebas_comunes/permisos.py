"""T29: la matriz de permisos (RF17) ruta por ruta y rol por rol, y el 401 del token de Keycloak.

RF17: «Una solicitud sin token válido recibe 401, mientras que una con token válido pero sin el rol requerido recibe 403».

Cada servicio declara en tests/test_permisos.py, para cada ruta de su tabla de I5 (test_aislamiento_i5.RUTAS), qué roles
entran: SI, PROPIOS (solo sobre lo suyo; hoy, solo el profesional) o nada (= 403). Sobre la clínica de aislamiento.py:
  - Sin sesión, con una cabecera que no es un id o con un usuario que no existe: 401. Usuario dado de baja: 403.
  - Rol sin permiso: 403. Rol con permiso, sobre datos válidos de su clínica: 2xx (control: el permiso sirve de verdad).
  - PROPIOS: lo suyo es 2xx; lo del colega (los ids `_colega`) es 404, como lo inexistente (no se revela que existe),
    y para el administrador lo del colega SÍ es 2xx: así el 404 se debe al permiso y no a una solicitud mal armada.
El modo desarrollo (cabecera X-Usuario-Id) solo reemplaza cómo se sabe QUIÉN llama; el token de verdad se prueba aparte,
con `probar_token`, firmando tokens con una llave propia en vez de levantar Keycloak.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError

from aislamiento import _usuario, construir_clinica, _plano

SI, PROPIOS = "sí", "solo los propios"
ROLES = ("plataforma", "admin", "recepcion", "profesional")


def comprobar_matriz(rutas: dict, matriz: dict) -> None:
    """Cada ruta tiene su fila, y cada fila nombra roles que existen con valores que existen."""
    assert set(matriz) == set(rutas), f"sin fila en la matriz: {sorted(set(rutas) - set(matriz))}; sobran: {sorted(set(matriz) - set(rutas))}"
    for ruta, fila in matriz.items():
        assert set(fila) <= set(ROLES) and set(fila.values()) <= {SI, PROPIOS}, f"{ruta}: {fila}"


def _como_colega(w):
    """La misma clínica, pero con la agenda del colega en el lugar de la del profesional que llama."""
    return SimpleNamespace(**{**vars(w), **{k[: -len("_colega")]: v for k, v in vars(w).items() if k.endswith("_colega")}})


def _usuarios(con, w):
    roles = {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}
    plataforma = _usuario(con, roles, None, "ADM_PLATAFORMA", "Plataforma")
    baja = _usuario(con, roles, w.clinica, "ADM_CLINICA", "Dado de baja")
    con.execute("UPDATE usuario SET activo = false WHERE id = %s", (baja,))
    return {"plataforma": plataforma, "admin": w.admin, "recepcion": w.recepcion, "profesional": w.usuario_prof}, baja


def _llamar(cliente, con, metodo, sol, cabeceras):
    sol = _plano(sol)
    with con.transaction(force_rollback=True):    # cada intento ve el mundo intacto
        return cliente.request(metodo, sol["url"], params=sol.get("params"), json=sol.get("json"), headers=cabeceras)


def comprobar_permisos(cliente, con, ruta: str, solicitud, fila: dict) -> None:
    metodo = ruta.split(" ", 1)[0]
    w = construir_clinica(con, "propia")
    usuarios, baja = _usuarios(con, w)
    llamar = lambda sol, cab: _llamar(cliente, con, metodo, sol, cab)
    sol = solicitud(w, w)

    # 401: no se sabe quién llama. 403: se sabe, pero ya no puede entrar.
    for cab in ({}, {"X-Usuario-Id": "no-es-un-id"}, {"X-Usuario-Id": str(uuid.uuid4())}):
        r = llamar(sol, cab)
        assert r.status_code == 401, f"{cab}: {r.status_code} {r.text[:200]}"
    r = llamar(sol, {"X-Usuario-Id": str(baja)})
    assert r.status_code == 403, f"dado de baja: {r.status_code} {r.text[:200]}"

    for rol in ROLES:
        r = llamar(sol, {"X-Usuario-Id": str(usuarios[rol])})
        if rol in fila:
            assert 200 <= r.status_code < 300, f"{rol} debería poder: {r.status_code} {r.text[:200]}"
        else:
            assert r.status_code == 403, f"{rol} no debería poder: {r.status_code} {r.text[:200]}"

    # «Solo los propios»: lo del colega no existe para él, y para el administrador sí.
    if PROPIOS in fila.values():
        ajena = solicitud(_como_colega(w), _como_colega(w))
        for rol, permiso in fila.items():
            r = llamar(ajena, {"X-Usuario-Id": str(usuarios[rol])})
            if permiso == PROPIOS:
                assert r.status_code == 404, f"{rol} alcanzó lo del colega: {r.status_code} {r.text[:200]}"
            else:
                assert 200 <= r.status_code < 300, f"{rol} debería alcanzar lo del colega: {r.status_code} {r.text[:200]}"


# ---------- El token (AUTH_MODO=keycloak) ----------

EMISOR = "http://keycloak.prueba/realms/medicitas"


class _JWKSFalso:
    """Hace de las llaves públicas del realm: la del "Keycloak" de la prueba, o un JWKS caído."""

    def __init__(self, publica, caido=False):
        self.publica, self.caido = publica, caido

    def get_signing_key_from_jwt(self, token):
        if self.caido:
            raise PyJWKClientConnectionError("sin conexión")
        return SimpleNamespace(key=self.publica)


def probar_token(cliente, con, monkeypatch, url: str, permitido: str, negado: str) -> None:
    """GET `url` con tokens de todo tipo. `permitido` y `negado` son roles de ROLES que la matriz deja y no deja entrar."""
    from medicitas_comun import sesion as modulo_sesion

    w = construir_clinica(con, "propia")
    usuarios, baja = _usuarios(con, w)
    llave, otra_llave = (rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2))
    monkeypatch.setenv("AUTH_MODO", "keycloak")
    monkeypatch.setenv("KEYCLOAK_ISSUER", EMISOR)
    monkeypatch.setattr(modulo_sesion, "_cliente_jwks", lambda: _JWKSFalso(llave.public_key()))

    def token(usuario=usuarios[permitido], firma=llave, **cambios):
        # En keycloak_sub la clínica de prueba guarda el mismo uuid del usuario (aislamiento._usuario).
        datos = {"sub": str(usuario), "iss": EMISOR, "typ": "Bearer", "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **cambios}
        return jwt.encode({k: v for k, v in datos.items() if v is not None}, firma, algorithm="RS256")

    def codigo(autorizacion):
        with con.transaction(force_rollback=True):
            return cliente.get(url, headers={"Authorization": autorizacion} if autorizacion else {}).status_code

    casos = {
        "token válido con el rol requerido": (f"Bearer {token()}", 200),
        "token válido sin el rol requerido": (f"Bearer {token(usuarios[negado])}", 403),
        "usuario dado de baja": (f"Bearer {token(baja)}", 403),
        "sin cabecera Authorization": (None, 401),
        "otro esquema (Basic)": (f"Basic {token()}", 401),
        "texto que no es un JWT": ("Bearer esto-no-es-un-token", 401),
        "firmado con otra llave": (f"Bearer {token(firma=otra_llave)}", 401),
        "vencido": (f"Bearer {token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))}", 401),
        "de otro emisor": (f"Bearer {token(iss='http://otro.idp/realms/x')}", 401),
        "un id_token y no uno de acceso": (f"Bearer {token(typ='ID')}", 401),
        "sin sub": (f"Bearer {token(sub=None)}", 401),
        "sub que no es de ningún usuario": (f"Bearer {token(sub=str(uuid.uuid4()))}", 401),
        "sin firma (alg none)": ("Bearer " + jwt.encode({"sub": str(usuarios[permitido]), "iss": EMISOR, "typ": "Bearer"}, None, algorithm="none"), 401),
    }
    obtenidos = {caso: codigo(aut) for caso, (aut, _) in casos.items()}
    # Y si no se pueden consultar las llaves, no es culpa del cliente: 503, no 401.
    monkeypatch.setattr(modulo_sesion, "_cliente_jwks", lambda: _JWKSFalso(None, caido=True))
    obtenidos["llaves del proveedor inalcanzables"] = codigo(f"Bearer {token()}")
    esperados = {caso: esperado for caso, (_, esperado) in casos.items()} | {"llaves del proveedor inalcanzables": 503}
    assert obtenidos == esperados, {c: (obtenidos[c], esperados[c]) for c in esperados if obtenidos[c] != esperados[c]}
