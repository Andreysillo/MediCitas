# Servicios del backend

MediCitas no es un monolito: el backend son tres servicios de Python (FastAPI) que se despliegan, se caen y
se reinician por separado. Cada uno es dueño de un grupo de requisitos.

| Servicio | Responsable | Requisitos | Escribe en |
|---|---|---|---|
| `agenda` | Persona A | RF5–RF13, RF20 | `horario_atencion`, `bloqueo_agenda`, `cita` |
| `plataforma` | Persona B | RF1–RF4, RF14–RF16 | `clinica`, `usuario`, `especialidad`, `servicio`, `profesional`, `profesional_servicio`, `paciente`, `nota_clinica` |
| `auditoria` | Persona B | RF19, RF21 | nada: solo lee |

RF17 (autenticación con Keycloak) es común a los tres. RF18 (bitácora) lo cumple el servicio que lee o
escribe el dato protegido, con un `INSERT` en `registro_auditoria` **dentro de la misma transacción**. Si la
bitácora fuera una llamada HTTP a otro servicio, una caída de la red dejaría lecturas sin registrar.

## Cómo se comunican

- El navegador habla con un solo origen. El nginx del contenedor `web` reparte `/api/agenda/`,
  `/api/plataforma/` y `/api/auditoria/` hacia cada servicio ([frontend/nginx.conf](../frontend/nginx.conf)).
- Los servicios **no se llaman entre sí**. Comparten la base de datos, pero cada tabla tiene un solo
  servicio que escribe en ella (la tabla de arriba). Leer las tablas de otro está permitido, porque las
  restricciones del motor (I1, I2, I5) protegen la consistencia sin importar quién escriba. Cuando existan
  los roles de base de datos (T19), cada servicio tendrá su usuario, con permiso de escritura solo sobre
  sus tablas.

## Qué trae cada servicio sin escribir nada

Todo sale de `crear_app()` en [comun/medicitas_comun/app.py](comun/medicitas_comun/app.py):

- `GET /salud`: el proceso vive. `GET /listo`: además alcanza la base (lo usa el healthcheck de Docker).
- Un pool de conexiones que sobrevive a un reinicio de Postgres. La dependencia `conexion` da una
  conexión por solicitud dentro de una transacción: COMMIT si la ruta termina bien, ROLLBACK si falla.
- Los errores del motor se traducen solos: exclusión (I1, I2) y único → 409; clave foránea y CHECK → 422.
  La respuesta incluye la restricción violada. Base caída → 503. Cualquier otro error → 500 con el id de
  la solicitud, sin la traza (la traza queda en el log).
- Logs en JSON, una línea por solicitud, con el `solicitud` que también ve nginx (`X-Request-ID`).
- Documentación interactiva en `http://localhost:8080/api/<servicio>/docs`.

`comun/` es solo infraestructura. Una regla de negocio va en el servicio dueño del requisito, aunque otro
servicio la necesite parecida.

## Quién hace la solicitud

Una ruta que necesita saber quién llama recibe `sesion: Sesion = Depends(sesion_de_clinica)` y toma de ahí la
clínica y el rol. **La clínica nunca se lee de la solicitud** (I5).

Todo pasa por `sesion_actual`, en [comun/medicitas_comun/sesion.py](comun/medicitas_comun/sesion.py). Una ruta no sabe
cómo se autenticó nadie: solo recibe el usuario, la clínica y el rol. Por eso agregar Keycloak no cambió ninguna ruta.

| `AUTH_MODO` | Quién dice la identidad | Dónde se usa |
|---|---|---|
| `keycloak` (por defecto) | Un JWT en `Authorization: Bearer ...` | El sistema real |
| `desarrollo` | La cabecera `X-Usuario-Id`, **sin validar: no es seguro** | Solo `pruebas-agenda` |
| Cualquier otro | Nadie: todo responde 401 | |

Con Keycloak, cada solicitud sigue estos pasos:

1. **Se valida el token:** la firma contra las llaves públicas del realm, el emisor, que no esté vencido y que sea un token
   de acceso (`typ: Bearer`). Un token que no pase responde 401.
2. **Se busca al usuario** por `keycloak_sub = sub` en la tabla `usuario`. De esa fila salen la clínica y el rol: la base es
   la fuente de verdad, no los roles que trae el token.
3. **Se revisa `activo`** en cada solicitud, así que una baja corta el acceso de inmediato (403), sin esperar a que el token
   venza.

Dos direcciones distintas, a propósito:

- `KEYCLOAK_ISSUER` es la dirección **pública** (`http://localhost:8080/auth/...`): el emisor escrito en el token, fijado con
  `KC_HOSTNAME` para que sea el mismo sin importar por dónde se pidió.
- `KEYCLOAK_JWKS_URL` es la dirección **interna** (`http://keycloak:8080/...`): de donde las APIs bajan las llaves.

Las llaves quedan en memoria. Si Keycloak se cae, los tokens ya emitidos siguen funcionando y no se pueden pedir nuevos. Si
además la API se reinicia y no tiene las llaves, responde 503, y se recupera sola cuando Keycloak vuelve.

Las pruebas de `pruebas-agenda` corren en modo `desarrollo`: comprueban las reglas de negocio, no el token. Las pruebas de
permisos con tokens reales son la tarea T29.

## Pruebas

Hay dos clases, y se distinguen por lo que necesitan para correr:

| | Unitarias (`tests/unitarias/`) | De integración (`tests/*.py`) |
|---|---|---|
| Qué prueban | La lógica propia del código: qué valida, en qué orden bloquea, qué invalida, cómo arma una consulta | La API contra la pila real: lo que decide el motor (solapes, claves foráneas, triggers), la concurrencia y la caché con Redis |
| Qué necesitan | **Nada**: ni base de datos ni Redis. Usan dobles (`tests/unitarias/dobles.py`) | Postgres con el esquema aplicado; las de caché, también Redis |
| Cuánto tardan | Menos de un segundo | Unos 15 segundos |

```bash
docker compose --profile pruebas run --rm --build pruebas-agenda                                    # las dos clases
docker compose --profile pruebas run --rm --no-deps pruebas-agenda python -m pytest tests/unitarias   # solo las unitarias, sin base
```

Cuál escribir: si lo que se decide lo decide el **código** (un orden, un rechazo, una invalidación), unitaria; si lo decide
el **motor** (que dos reservas simultáneas del mismo espacio terminen en un solo 201), integración, porque un doble no puede
reproducir al motor. El cálculo de los espacios libres es una consulta SQL, así que sus resultados también se prueban con
integración; las unitarias cubren lo que la rodea.

Una prueba marcada `xfail(strict=True)` es una exigencia que el sistema **aún no cumple** (hoy, I6: la bitácora append-only
en el motor). Se reporta como `xfailed` en vez de ocultarse, y cuando se cumpla falla a propósito para avisar que hay que
quitarle la marca.

En las de integración, `tests/conftest.py` arma un "mundo" mínimo por prueba (dos clínicas, usuarios de cada rol,
profesionales, un paciente) y da `mundo.cita(...)` para crear citas. Casi todas se deshacen con ROLLBACK, así que no
dependen de la semilla ni dejan datos; las que necesitan datos confirmados (concurrencia y caché) borran lo que crean.

### Aislamiento entre clínicas (I5, T26)

Cada servicio tiene `tests/test_aislamiento_i5.py`: una tabla con **todas** sus rutas y cómo se arma cada solicitud.
El motor que las ataca es uno solo, [pruebas_comunes/aislamiento.py](pruebas_comunes/aislamiento.py), que el Dockerfile
copia junto a las pruebas (fuera de `comun/` para que no llegue a la imagen de producción). Arma dos clínicas iguales:
la víctima lleva un "canario" (una palabra única) en cada texto. Desde cada rol de la otra clínica, y como administrador
de plataforma, prueba en cada ruta:

| Intento | Qué se exige |
|---|---|
| Ids ajenos en el camino, la consulta o el cuerpo (solos o mezclados con propios) | La misma respuesta, código **y** mensaje, que con ids inventados: no se revela que el dato existe |
| Buscar por texto (identificación del paciente ajeno) | Ninguna respuesta trae el canario ni ids ajenos |
| `clinica_id` en la consulta y el cuerpo, cabecera `X-Clinica-Id` | No cambia nada: la clínica sale de la sesión |
| Cualquier escritura | Los datos de la víctima quedan idénticos (un md5 por tabla con `clinica_id`; una tabla nueva queda vigilada sola) |
| Lecturas propias | Lo que el atacante ve de su clínica es idéntico exista o no la víctima (atrapa un conteo que suma otra clínica) |
| Control | Con los ids propios la ruta sí funciona para algún rol: los 404 son por la clínica, no por una solicitud mal armada |

**Una ruta nueva que no se agregue a la tabla hace fallar `test_todas_las_rutas_estan_en_el_barrido`.** Para agregarla:
una línea `"MÉTODO /camino/{param}": lambda w, ref: dict(url=..., params=..., json=...)`, con `w` la clínica de lo que
se toca (ids del camino) y `ref` la de lo que se menciona (consulta y cuerpo). Validado plantando 10 fugas distintas en los
tres servicios (filtros de clínica quitados, `?clinica_id=` aceptado, 403 contra 404, un mensaje distinto, un reporte que
suma todas las clínicas): las 10 hacen fallar el barrido.

### Matriz de permisos y token (RF17, T29)

Cada servicio tiene `tests/test_permisos.py` con la matriz del enunciado escrita como tabla: por ruta, qué roles entran
(`SI`, `PROPIOS` o ausente, que significa 403). Reutiliza las solicitudes de `test_aislamiento_i5.RUTAS`, así que una
ruta nueva necesita su fila en las dos tablas. El motor está en [pruebas_comunes/permisos.py](pruebas_comunes/permisos.py) y exige:

- **401** sin sesión, con una cabecera que no es un id o con un usuario que no existe. **403** si fue dado de baja.
- **403** para el rol sin permiso, y **2xx** para el rol con permiso sobre datos válidos de su clínica (si no, una ruta
  rota pasaría por "segura").
- **`PROPIOS`**: lo del colega (el segundo profesional del mundo) es 404 como lo inexistente; para el administrador, lo
  mismo es 2xx.
- **El token de verdad** (`AUTH_MODO=keycloak`), firmando tokens con una llave propia en vez de levantar Keycloak:
  401 sin `Authorization`, con otro esquema, con basura, con otra firma, vencido, de otro emisor, un id_token, sin
  `sub`, con un `sub` desconocido o sin firma (`alg: none`); 403 con el rol equivocado o dado de baja; 503 si no se
  pueden consultar las llaves del proveedor.

RF20 (agenda del día) y RF21 (reportes) no están en la matriz del enunciado; las filas dicen lo que decidimos.
Validado con 17 permisos rotos a mano, incluidos 6 en `comun/sesion.py`: los 17 hacen fallar las pruebas.

## Reglas entre servicios y tareas

- **Bloqueo de fila sobre el profesional (y el paciente).** Toda operación que cambie lo que el profesional puede
  atender o lo que tiene reservado toma `FOR NO KEY UPDATE` sobre su fila de `profesional`: un bloqueo nuevo, quitar un
  bloque de horario, reservar. La reserva toma además la del paciente, SIEMPRE en ese orden (profesional, luego
  paciente). Con eso nunca queda una cita dentro de un bloqueo sin que el sistema lo sepa (I3) y, sobre todo, no hay deadlocks entre reservas que
  disputan el mismo espacio: medido con 8 clientes y bloqueo compartido (`FOR SHARE`), varios abortaban con 40P01,
  porque Postgres inserta la entrada del índice de exclusión antes de revisarla y cada inserción veía la de la otra.
  La reprogramación usa el mismo camino: toma al profesional de destino y al paciente, y después la cita. El profesional
  de origen no hace falta: liberar un espacio no pone en riesgo nada.

## Agregar una ruta

En el servicio que corresponda, un archivo por grupo de requisitos, por ejemplo `agenda/app/disponibilidad.py`:

```python
from fastapi import APIRouter, Depends
from medicitas_comun import conexion

router = APIRouter(prefix="/disponibilidad", tags=["RF7"])

@router.get("/{profesional_id}")
def espacios(profesional_id: str, con=Depends(conexion)):
    return con.execute("SELECT ...", (profesional_id,)).fetchall()
```

y en `agenda/app/main.py`: `app.include_router(disponibilidad.router)`. Una dependencia nueva va en el
`requirements.txt` del servicio, con versión exacta.

## Correr un servicio fuera de Docker

```bash
cd servicios
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e comun -r agenda/requirements.txt
DATABASE_URL=postgresql://medicitas:<clave>@localhost:5432/medicitas uvicorn --app-dir agenda app.main:app --reload
```

La base del compose no publica su puerto. Para eso se agrega `ports: ["127.0.0.1:5433:5432"]` al
servicio `db` en un `compose.override.yml` propio, que no se versiona.
