# MediCitas

Sistema de gestión de citas para varias clínicas (multi-tenant): cada clínica ve solo lo suyo. Tres APIs en FastAPI
(`agenda`, `plataforma`, `auditoria`) sobre PostgreSQL 16, Redis como caché, Keycloak para la identidad y nginx como
gateway del frontend (React + Vite). Todo levanta con un solo comando de Docker Compose.

## Contenido

- [Documentación](#documentación)
- [Levantar el sistema](#levantar-el-sistema)
- [Probar el sistema](#probar-el-sistema)
- [Rutas de la API](#rutas-de-la-api)
- [Arquitectura y decisiones de diseño](#arquitectura-y-decisiones-de-diseño)
- [Desarrollo del frontend](#desarrollo-del-frontend)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Declaración de uso de inteligencia artificial](#declaración-de-uso-de-inteligencia-artificial)

## Documentación

| Qué buscas | Dónde está |
|---|---|
| **Rutas de las API documentadas** (cuerpo, roles y errores de cada ruta) | [docs/api.md](docs/api.md) |
| Diseño de datos: ER, diccionario, 3FN, aislamiento transaccional, índices y caché | [docs/diseno-datos.md](docs/diseno-datos.md) |
| Diseño de seguridad: comparación de multi-tenancy, identidad, roles de base de datos y bitácora | [docs/diseno-seguridad.md](docs/diseno-seguridad.md) |
| Documento de diseño completo (las dos partes anteriores) en PDF | [docs/MediCitas_Documento de diseno.pdf](docs/MediCitas_Documento%20de%20diseno.pdf) |
| Modelo lógico: borrador previo, que los dos documentos de diseño amplían | [docs/diseno-modelo-logico.md](docs/diseno-modelo-logico.md) |
| Base de datos: migraciones, semilla, índices y roles | [db/README.md](db/README.md) |
| Servicios: reglas comunes, cómo agregar una ruta y las pruebas | [servicios/README.md](servicios/README.md) |
| Servicio de agenda: reserva, ciclo de vida de la cita y caché | [servicios/agenda/README.md](servicios/agenda/README.md) |
| Enunciado del proyecto | [docs/enunciado.md](docs/enunciado.md) |

## Levantar el sistema

Requisito: Docker Desktop (o Docker con Compose) **encendido**.

```bash
cp .env.example .env          # la primera vez; después, cambiar las contraseñas
docker compose up -d --build  # construye y levanta todo; la primera vez tarda unos minutos
docker compose ps             # todo "healthy"; "migraciones" en "Exited (0)"
```

Cuando termine, el sistema está en **http://localhost:8080**.

Si ya tenías un `.env` de antes, compáralo con `.env.example`: cada variable nueva que falte detiene el compose con un
mensaje `falta X en .env`. Las últimas en agregarse fueron `AGENDA_DB_PASSWORD`, `PLATAFORMA_DB_PASSWORD` y
`AUDITORIA_DB_PASSWORD` (los roles de cada servicio, migración 011). Con una base que ya existía, `up` aplica solo las
migraciones nuevas y conserva los datos.

| Contenedor | Qué hace |
|---|---|
| `db` | PostgreSQL 16. Publicado solo en el equipo local, `127.0.0.1:${PUERTO_BD}` (5423), para pgAdmin o psql |
| `migraciones` | Aplica el esquema y la semilla nuevos, habilita los roles de cada servicio, y termina ([db/](db/README.md)) |
| `keycloak` | Proveedor de identidad (RF17). Importa `keycloak/realm-export.json` al arrancar: nada se configura a mano |
| `redis` | Caché de la disponibilidad (RF7). Sin disco y sin puerto publicado: si se apaga, agenda sigue desde la base |
| `agenda`, `plataforma`, `auditoria` | Las tres APIs ([servicios/](servicios/README.md)). Cada una entra a la base con su propio rol |
| `web` | El frontend compilado y el gateway hacia las APIs y Keycloak, en http://localhost:8080 |

Comandos útiles:

- `docker compose logs -f agenda`: logs en JSON de un servicio.
- `docker compose down`: apaga todo y conserva los datos. `down -v`: también borra la base.
- `docker compose --profile herramientas up -d`: agrega pgAdmin en http://localhost:5050.

## Probar el sistema

**El frontend (http://localhost:8080) es una demostración con datos en memoria: no llama a las APIs.** Sirve para ver
las pantallas y los permisos por rol ("Probar la demo" y elegir un usuario), pero lo que se haga ahí no llega a la base
y se pierde al recargar. Ver [Desarrollo del frontend](#desarrollo-del-frontend).

**El sistema real se prueba contra las APIs**, con un token de Keycloak, igual que lo haría un cliente.

### Usuarios de prueba

Los 18 usuarios son los mismos de la semilla de la base (su `id` en Keycloak es igual al `keycloak_sub` que ya trae
`db/seed/001_catalogos.sql`), todos con la contraseña **`medicitas123`**. Por ejemplo:

| Usuario (Keycloak) | Rol | Clínica |
|---|---|---|
| `plataforma` | ADM_PLATAFORMA | — |
| `san-rafael-admin` | ADM_CLINICA | Clínica San Rafael |
| `san-rafael-recepcion` | RECEPCION | Clínica San Rafael |
| `san-rafael-laura-mendez` | PROFESIONAL | Clínica San Rafael |

(y lo mismo para `del-valle-*` y `los-robles-*`; la lista completa está en
[keycloak/realm-export.json](keycloak/realm-export.json)). Consola de administración de Keycloak:
http://localhost:8080/auth/admin (usuario y contraseña de `KEYCLOAK_ADMIN*` en `.env`; no son credenciales de la aplicación).

### Reservar una cita paso a paso

Los comandos son de bash (en Windows, Git Bash) y necesitan `jq`.

```bash
# 1. Token de un usuario de prueba
TOKEN=$(curl -s http://localhost:8080/auth/realms/medicitas/protocol/openid-connect/token   -d grant_type=password -d client_id=medicitas-api   -d username=san-rafael-recepcion -d password=medicitas123 | jq -r .access_token)

# 2. Catálogo: un servicio y un profesional que lo atienda
curl -s http://localhost:8080/api/plataforma/servicios      -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8080/api/plataforma/profesionales  -H "Authorization: Bearer $TOKEN"

# 3. Espacios libres (RF7) y reserva (RF9), con un paciente de GET /api/plataforma/pacientes
curl -s "http://localhost:8080/api/agenda/profesionales/<profesional_id>/disponibilidad?servicio_id=<servicio_id>&fecha=2026-11-20"   -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8080/api/agenda/citas -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d '{"paciente_id":"<paciente_id>","profesional_id":"<profesional_id>","servicio_id":"<servicio_id>","inicio":"<un espacio del paso 3>"}'
```

Sin token, cualquier ruta responde 401. Con `san-rafael-recepcion`, `/api/auditoria/bitacora` responde 403: la bitácora es solo
del administrador de la clínica. (`grant_type=password` es cómodo para pruebas; el login real del frontend sería
*authorization code* + PKCE con el *client* `medicitas-web`, que el realm ya trae configurado.)

### Pruebas automáticas

**Un solo comando corre todas las pruebas** (unitarias y de integración de los tres servicios), contra la misma base real:

```bash
bash pruebas.sh
```

No hay que preparar datos: las pruebas arman los suyos. Si un servicio falla, igual se corren los demás y el script termina
con error; si pasan los tres, termina bien (tarda un par de minutos la primera vez, porque construye las imágenes).

Para correr un solo servicio:

```bash
docker compose --profile pruebas run --rm pruebas-agenda        # o pruebas-plataforma, pruebas-auditoria
```

Qué cubre cada una: [servicios/README.md](servicios/README.md#pruebas).

## Rutas de la API

**Rutas de las API documentadas: [docs/api.md](docs/api.md)**, con cada ruta, su cuerpo, sus roles y sus errores.
La referencia interactiva, generada desde el código, está en cada servicio:

| Servicio | Prefijo (por el gateway) | Referencia interactiva | Qué cubre |
|---|---|---|---|
| Agenda | `/api/agenda` | http://localhost:8080/api/agenda/docs | Horarios, bloqueos, disponibilidad y citas (RF5 a RF13, RF20) |
| Plataforma | `/api/plataforma` | http://localhost:8080/api/plataforma/docs | Clínicas, usuarios, catálogo, pacientes y notas (RF1 a RF4, RF14 a RF16) |
| Auditoría | `/api/auditoria` | http://localhost:8080/api/auditoria/docs | Bitácora y reportes (RF19, RF21) |

## Arquitectura y decisiones de diseño

El razonamiento completo, con alternativas y trade-offs, está en [docs/diseno-datos.md](docs/diseno-datos.md) y
[docs/diseno-seguridad.md](docs/diseno-seguridad.md). Aquí, lo esencial.

### Las citas no se solapan: lo garantiza el motor (I1 e I2)

Un `if` en el código no basta: si dos recepcionistas reservan el mismo espacio a la vez, ambas consultas ven
el espacio libre y las dos insertan. Por eso la regla vive en PostgreSQL, en
[db/migrations/004_citas.sql](db/migrations/004_citas.sql):

```sql
EXCLUDE USING gist (profesional_id WITH =, tstzrange(inicio, fin, '[)') WITH &&)
  WHERE (estado IN ('RESERVADA','ATENDIDA','AUSENTE'))
```

Se lee: "no puede haber dos citas del mismo profesional con rangos de tiempo que se traslapan, mirando solo
las que ocupan espacio".

- `'[)'` incluye el inicio y excluye el fin, así que 9:00–9:30 y 9:30–10:00 pueden convivir.
- El `WHERE` hace que cancelar o reprogramar libere el espacio sin borrar la cita (I7).
- Hay una exclusión gemela para el paciente (I2).
- Con concurrencia, la segunda transacción espera a la primera y, si chocan, falla con `23P01`; la API lo
  traduce a **409**.

### Una clínica nunca se mezcla con otra: claves foráneas compuestas (I5)

Cada tabla lleva `clinica_id`. Las claves foráneas incluyen la clínica: `cita (clinica_id, profesional_id)`
apunta a `profesional (clinica_id, id)`.

Con una clave simple, el motor solo comprobaría que el profesional exista, y una cita de la clínica A podría
quedar atada a un profesional de la B. Con la compuesta, el profesional debe ser de la **misma** clínica de la
cita; si no, el motor rechaza (`23503`, que la API traduce a 422).

Esto garantiza que **los datos son coherentes**, no **quién** puede verlos. De eso se encarga el token de
Keycloak, que dice la clínica del usuario, y el código que filtra por ella. Son dos capas: si el código se
equivoca, las claves compuestas impiden que los datos se mezclen.

### Migraciones: el mismo esquema en todos lados

[db/aplicar.sh](db/aplicar.sh) aplica los archivos de `db/migrations/` y `db/seed/` en orden, cada uno una
sola vez (lo anota en `schema_migrations`), completo o nada, y se detiene si algo falla. Lo corre el servicio
`migraciones` del compose antes de las APIs: así la base de cualquier entorno (la tuya, la del equipo, la del
servidor) llega al mismo esquema, y ninguna API arranca sobre uno incompleto. Un cambio nuevo es siempre la
migración siguiente; nunca se edita una ya aplicada.

### Servicios separados, no un monolito

`agenda`, `plataforma` y `auditoria` son contenedores distintos. Si uno cae, los demás siguen: sin `agenda`
no se puede reservar, pero sí gestionar pacientes o consultar la bitácora. El punto compartido es la base de
datos: si cae, las tres responden 503 hasta que vuelve. Además, cada persona edita su propia carpeta sin
pisar a la otra. Los servicios no se llaman entre sí, y cada tabla la escribe un solo servicio
([servicios/](servicios/README.md)).

### nginx: servidor del frontend y gateway

El contenedor `web` hace dos cosas: sirve los archivos del frontend y reenvía `/api/<servicio>/` al
contenedor que corresponde, así el navegador habla con un solo origen.

Por defecto nginx resuelve los nombres de sus destinos al arrancar y **se niega a iniciar** si alguno no
responde. Aquí el destino va en una variable ([frontend/nginx.conf](frontend/nginx.conf)), y se resuelve en
cada solicitud: la página arranca aunque una API esté caída, esa API responde 502 y las demás siguen. Cuando
vuelve, funciona sin reiniciar nada.

### Identidad: Keycloak, no código propio

Las APIs no implementan login: lo hace Keycloak, que corre como un contenedor más. Su realm (`medicitas`), roles,
*clients* y usuarios de prueba se importan de [keycloak/realm-export.json](keycloak/realm-export.json) al arrancar. Cada
API valida el token contra las llaves del realm y busca al usuario en la base, de donde salen su clínica y su rol. Por qué
así (y por qué no se valida `aud`): [docs/diseno-seguridad.md](docs/diseno-seguridad.md#2-identidad-delegada-keycloak).

### Caché de disponibilidad (Redis)

RF7 (qué horas libres tiene un profesional) es la consulta que más veces se ejecuta, y calcularla en PostgreSQL cuesta.
Por eso se sirve desde Redis, que corre en el Compose sin disco y sin puerto publicado. **Redis solo guarda copias**: la verdad
siempre está en PostgreSQL, y si Redis se apaga, la agenda sigue funcionando desde la base, algo más lenta.

#### Cómo pensarla: una pizarra con hojas

Imagina la recepción de la clínica:

- **La agenda oficial es PostgreSQL.** Siempre es correcta, pero contestar "¿qué horas libres tiene la Dra. Méndez el lunes?"
  obliga a revisar horarios, bloqueos y citas.
- **Redis es una pizarra con hojas ya resueltas**, por ejemplo: «Dra. Méndez · lunes 16 · Control de 15 min → libres 8:00, 8:15,
  8:30…». Leer una hoja es casi instantáneo.
- **Cada hoja es la copia de UNA consulta**. Su título es la *clave*: clínica, profesional, servicio, duración, fecha y un número
  de edición. Si cualquiera de esos datos cambia, el título es otro y se busca (o se crea) otra hoja.
- **Cada profesional tiene un letrero con su número de edición.** Reservar, cancelar, reprogramar o cambiar sus horarios o
  bloqueos sube el letrero (de 7 a 8). Las hojas de la edición 7 siguen en la pizarra, pero nadie las vuelve a buscar: todos
  piden la 8. Así, **un solo número invalida todas las fechas y servicios de ese profesional**, sin buscar hoja por hoja.
- **Un conserje tira cada hoja a los 5 minutos** (el *TTL*). No repone nada ni vuelve a una versión anterior: solo la tira, y la
  siguiente consulta la recalcula. Es una red de seguridad por si un letrero no llegó a subir; no es lo que mantiene correcta
  la caché.

Un ejemplo, con Ana y Beto que consultan, y Luis que reserva:

| Hora | Qué ocurre | Letrero | Hojas en la pizarra |
|---|---|---|---|
| 9:00 | Ana consulta el lunes 16. No hay hoja: se calcula en PostgreSQL y se cuelga la hoja | 7 | edición 7 |
| 9:01 | Beto consulta lo mismo: lee la hoja, sin calcular | 7 | edición 7 |
| 9:02 | Luis reserva las 8:00. Primero la cita queda **confirmada** en PostgreSQL; luego sube el letrero; recién entonces se le responde | 8 | edición 7 (invisible) |
| 9:03 | Ana vuelve a consultar: busca la edición 8, no hay hoja, calcula, ya no ve las 8:00 libres y cuelga la hoja nueva | 8 | edición 7, edición 8 |
| 9:05 | El conserje tira la hoja de la edición 7 | 8 | edición 8 |

Por eso la caché **no miente** (invariante I8): quien reserva nunca ve su espacio libre al volver a consultar, y no hay que
esperar a que venza nada. El orden importa: si el letrero subiera *antes* de confirmar la cita, alguien podría colgar una hoja
nueva sin ver todavía la reserva, y esa hoja falsa se quedaría.

Tres cosas que suelen confundirse:

1. **Cambiar la duración de un servicio no sube el letrero.** La duración está en el título de la hoja, así que las consultas
   piden hojas nuevas por su cuenta. Por eso `plataforma` puede editar servicios sin saber que existe Redis.
2. **Si la pizarra se llena,** Redis tira hojas primero y nunca letreros: si un letrero desapareciera, volvería a 0 y podrían
   reaparecer hojas viejas.
3. **Redis no guarda nada en disco, a propósito.** Al reiniciarse arranca con la pizarra vacía, y eso siempre es correcto. Un
   respaldo traería hojas que quizá ya no son verdad.

Con los índices de la base, una hoja ahorra unos 2 ms por consulta; sin ellos, más del doble
([medición](servicios/agenda/README.md#qué-se-midió-t34)). Todas las decisiones, la incoherencia que queda y por qué:
[servicios/agenda/README.md](servicios/agenda/README.md#caché-de-disponibilidad-rf7-i8).

## Desarrollo del frontend

> El frontend todavía usa datos de prueba en memoria; cada función de `frontend/src/api/` se cambiará por un
> `fetch` a `/api/<servicio>/...`.

Requisito: Node.js 22 o superior.

```bash
cd frontend
npm install      # solo la primera vez o cuando cambie package.json
npm run dev      # abre http://localhost:5173
```

- La raíz (`#/`) es la landing promocional (producto ficticio). El logo de la barra lateral regresa a ella.
- **"Probar la demo"** abre el ingreso: se elige rol, clínica y usuario de prueba. Dentro solo aparece lo que ese rol puede ver, como pasará luego con el token de Keycloak. **"Cambiar de rol"** vuelve a esa pantalla y **"Salir"** regresa a la landing.
- Los cambios hechos en la página viven en memoria: al recargar vuelven los datos de prueba.
- `npm run build` verifica los tipos y compila. Conviene correrlo antes de hacer commit.

## Estructura del repositorio

```
compose.yml    levanta todo el sistema; .env.example trae las variables que necesita
frontend/      React + Vite; en Docker lo sirve nginx (nginx.conf)
servicios/     las tres APIs (FastAPI), su infraestructura común y las pruebas compartidas
db/            migraciones, semilla y pruebas del esquema
keycloak/      configuración del realm (identidad y roles), importada al arrancar
docs/          enunciado, referencia de la API y documentos de diseño
```

## Declaración de uso de inteligencia artificial

Durante el desarrollo usamos **Claude Code** (de Anthropic, dentro de VS Code), con modelos de la familia Claude Opus y
Sonnet. Lo declaramos aquí, como pide el enunciado, y describimos qué hizo la herramienta y qué decidió y comprobó el grupo.

### Cómo se usó

| Uso | Qué hizo la herramienta | Qué hizo el grupo |
|---|---|---|
| **Preguntas de diseño antes de programar** | Antes de escribir cada pieza importante planteó la decisión como pregunta, con alternativas y su costo: por ejemplo, si un invariante debía vivir en el motor o en la aplicación, o cuánto aislamiento pedirle a la transacción de reserva | Eligió entre las alternativas y fijó el alcance (por ejemplo, dejar el frontend como demostración con datos en memoria y no conectarlo a las APIs en esta etapa) |
| **Repasar y explicar temas técnicos de forma simple** | Explicó conceptos con analogías y ejemplos concretos (la pizarra de la caché, dos recepcionistas sobre el mismo espacio, el orden de los bloqueos y el deadlock) y ayudó a repasar para la defensa | Pidió esas explicaciones para poder defender cada decisión por su cuenta; varias quedaron en esta documentación |
| **Código, pruebas y documentación** | Escribió borradores de código (reserva transaccional, disponibilidad, caché con Redis, triggers y migraciones), de las pruebas (unitarias, concurrencia, barrido de aislamiento, matriz de permisos) y de la documentación, incluido el documento de diseño de datos | Revisó, ejecutó y corrigió lo producido, y confirmó cada cambio con un commit propio |
| **Frontend** | Ayudó a construirlo (landing, ingreso por rol y pantallas con sus permisos) a partir de lo que se le pidió, y a pulirlo | Aportó las inspiraciones y las ideas, y definió cómo debía ser el frontend; revisó el resultado y pidió los ajustes |
| **Verificación** | Corrió las pruebas contra la base real, midió los índices y la caché, y comprobó que las pruebas fallan cuando se rompe a propósito la regla que cubren | Decidió qué se midió y qué cuenta como correcto; contrastó lo que dijo la herramienta con el comportamiento observado (por ejemplo, una afirmación suya sobre qué responde la API cuando cae la base se corrigió contra lo medido) |

### Lo que la herramienta no hizo

- **No hizo commits.** Todos los commits del repositorio los hicieron las personas del grupo, desde su cuenta.
- **No decidió por el grupo.** Las decisiones de diseño, el alcance y las compensaciones aceptadas (lo que se sacrificó en cada una está escrito en los documentos de diseño) las tomó el grupo.
- **No sustituye la defensa.** Cada integrante responde de forma individual por lo que está en este repositorio.
