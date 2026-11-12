# Referencia de la API

Las rutas que hoy existen, una por sección: qué hace, quién puede llamarla, qué recibe, qué devuelve y con qué errores
responde. La documentación interactiva, generada desde el código, está en `/api/<servicio>/docs`. Este documento la
resume y agrega lo que no se ve allí: los roles, las reglas y el porqué de cada error.

| Servicio | Prefijo | Requisitos |
|---|---|---|
| Agenda | `/api/agenda` | RF5 a RF13 |
| Plataforma | `/api/plataforma` | RF1 y RF14 (RF2 a RF4, RF15 y RF16 aún sin documentar aquí) |
| Auditoría | `/api/auditoria` | RF19 y RF21, aún sin rutas |

## Convenciones

**Base.** Todo pasa por el gateway: `http://localhost:8080`. Las APIs no publican puertos propios.

**Autenticación.** Cada solicitud lleva `Authorization: Bearer <token>`. El token lo emite Keycloak; cómo pedirlo está en
el [README](../README.md#identidad-keycloak). La clínica y el rol salen del usuario dueño del token, **nunca de la
solicitud**: enviar un `clinica_id` no sirve de nada (I5).

**Roles.** `ADM_PLATAFORMA` (plataforma), `ADM_CLINICA` (administrador de clínica), `RECEPCION` y `PROFESIONAL`.

**Tipos.**

| Tipo | Formato | Ejemplo |
|---|---|---|
| id | UUID | `99578cd7-9958-95f1-a8e6-e0750f1c9e18` |
| instante | ISO 8601 **con zona**. Sin zona es 422, porque sería ambiguo | `2026-11-16T08:00:00-06:00`, `2026-11-16T14:00:00Z` |
| fecha | `AAAA-MM-DD`, día local de la clínica | `2026-11-16` |
| hora | `HH:MM`, hora local de la clínica | `08:00` |

Las respuestas devuelven los instantes en UTC (`Z`).

**Errores.** Todos tienen la misma forma:

```json
{ "detalle": "Ese espacio ya fue tomado", "restriccion": "cita_sin_solape_profesional" }
```

`restriccion` solo aparece cuando la regla la hizo cumplir el motor. Un 422 por datos mal formados trae además `campos`:

```json
{ "detalle": "Los datos enviados no son válidos",
  "campos": [{ "campo": "fin", "problema": "Extra inputs are not permitted" }] }
```

Estos errores valen para todas las rutas, y no se repiten en cada sección:

| Código | Cuándo |
|---|---|
| 401 | Sin token, token vencido, mal firmado o que no es de acceso, o usuario desconocido |
| 403 | El rol no puede hacer esto, el usuario está dado de baja, o el administrador de plataforma pide datos clínicos |
| 404 | Lo que indica la URL no existe **en tu clínica**. Algo de otra clínica responde igual que algo inexistente: no se revela que existe. Un id de otra clínica en el **cuerpo** da 422 |
| 422 | Datos inválidos: formato, campos que sobran o una regla del negocio |
| 503 | Algo transitorio: la base, Keycloak o un conflicto entre transacciones. Se puede repetir la solicitud |
| 500 | Error no previsto. Trae `solicitud`, el id con que se busca en los logs |

Cada servicio expone además `GET /salud` (el proceso vive) y `GET /listo` (alcanza la base), sin token. Los usan los
healthchecks.

---

## Agenda

### Listar profesionales gestionables

`GET /api/agenda/profesionales` · RF5 · `ADM_CLINICA`, `PROFESIONAL`

Los profesionales cuyo horario puede gestionar quien llama: el administrador ve todos los de su clínica, y un
profesional solo se ve a sí mismo.

**Respuesta 200**

```json
[{ "id": "99578cd7-9958-95f1-a8e6-e0750f1c9e18", "nombre": "Dra. Laura Méndez", "especialidad": "Medicina general" }]
```

### Ver el horario semanal

`GET /api/agenda/profesionales/{profesional_id}/horarios` · RF5 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

Los bloques de atención, ordenados por día y hora. Un día puede tener varios bloques: la jornada partida son dos.

**Respuesta 200**

```json
[
  { "id": "cc97463f-395f-4b7a-b2e2-9b2e7e35a75c", "profesional_id": "99578cd7-…", "dia_semana": 1, "hora_inicio": "08:00", "hora_fin": "12:00" },
  { "id": "043c4fe0-8efb-47b5-8b87-9ee6f97b020d", "profesional_id": "99578cd7-…", "dia_semana": 1, "hora_inicio": "13:00", "hora_fin": "17:00" }
]
```

**Errores:** 404 si el profesional no es de tu clínica, o si eres profesional y no es el tuyo.

### Agregar un bloque de horario

`POST /api/agenda/profesionales/{profesional_id}/horarios` · RF5 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

| Campo | Tipo | Regla |
|---|---|---|
| `dia_semana` | entero | 1 lunes … 7 domingo |
| `hora_inicio` | hora | |
| `hora_fin` | hora | Posterior a `hora_inicio` |

```json
{ "dia_semana": 3, "hora_inicio": "14:00", "hora_fin": "18:00" }
```

**Respuesta 201:** el bloque creado, con la misma forma que en el listado.

| Error | Cuándo |
|---|---|
| 409 `horario_sin_solape` | Se solapa con otro bloque del mismo día |
| 422 | `hora_fin` no es posterior a `hora_inicio`, o la hora no tiene el formato `HH:MM` |

### Quitar un bloque de horario

`DELETE /api/agenda/horarios/{horario_id}` · RF5 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

Rige hacia adelante: **no cancela citas**. Devuelve las reservas que quedaron fuera de toda atención, para que recepción
las reprograme.

**Respuesta 200**

```json
{ "conflictos": [ { "id": "…", "profesional_id": "…", "paciente_id": "…", "servicio_id": "…",
                    "inicio": "2026-11-18T20:00:00Z", "fin": "2026-11-18T20:30:00Z", "estado": "RESERVADA",
                    "paciente": "Ana Solís", "servicio": "Consulta general" } ] }
```

### Ver los bloqueos

`GET /api/agenda/profesionales/{profesional_id}/bloqueos` · RF6 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

Los bloqueos vigentes o futuros, cada uno con las citas reservadas que caen dentro (`conflictos`, con la misma forma que
arriba).

### Crear un bloqueo

`POST /api/agenda/profesionales/{profesional_id}/bloqueos` · RF6 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

Vacaciones o permisos. Retira la disponibilidad desde ya, pero **no cancela citas**: las que caen dentro vuelven en
`conflictos`.

| Campo | Tipo | Regla |
|---|---|---|
| `inicio` | instante | |
| `fin` | instante | Posterior a `inicio`, y todavía no pasado |
| `motivo` | texto | 3 a 200 caracteres |

```json
{ "inicio": "2026-12-21T00:00:00-06:00", "fin": "2027-01-04T00:00:00-06:00", "motivo": "Vacaciones" }
```

**Respuesta 201**

```json
{ "id": "…", "profesional_id": "…", "inicio": "2026-12-21T06:00:00Z", "fin": "2027-01-04T06:00:00Z",
  "motivo": "Vacaciones", "conflictos": [] }
```

**Errores:** 422 si el bloqueo ya terminó.

### Quitar un bloqueo

`DELETE /api/agenda/bloqueos/{bloqueo_id}` · RF6 · `ADM_CLINICA`, `PROFESIONAL` (solo el suyo)

**Respuesta 204**, sin cuerpo.

### Disponibilidad de un profesional

`GET /api/agenda/profesionales/{profesional_id}/disponibilidad` · RF7 · `ADM_CLINICA`, `RECEPCION`, `PROFESIONAL`

Las horas a las que puede **empezar** una cita de ese servicio con ese profesional, en esa fecha. Tiene en cuenta el
horario, la duración del servicio, los bloqueos, las citas vigentes y lo que ya pasó. Se ofrece un inicio cada 15
minutos. Se sirve desde la caché Redis, que nunca contradice a la base
([cómo](../servicios/agenda/README.md#caché-de-disponibilidad-rf7-i8)).

| Parámetro | Tipo | Regla |
|---|---|---|
| `servicio_id` | id | Obligatorio |
| `fecha` | fecha | Obligatorio. Día local de la clínica |
| `ignorar_cita` | id | Opcional. Cuenta como libre el espacio de esa cita: se usa al reprogramarla. No pasa por la caché |

```
GET /api/agenda/profesionales/99578cd7-…/disponibilidad?servicio_id=9f79d973-…&fecha=2026-11-16
```

**Respuesta 200**

```json
{ "profesional_id": "99578cd7-…", "servicio_id": "9f79d973-…", "fecha": "2026-11-16", "duracion_minutos": 15,
  "espacios": ["2026-11-16T14:00:00Z", "2026-11-16T14:15:00Z", "2026-11-16T14:30:00Z"] }
```

| Error | Cuándo |
|---|---|
| 404 | El servicio o el profesional no existen en tu clínica, o están desactivados |
| 422 | El profesional no atiende ese servicio, o la fecha no es válida |

### Disponibilidad por servicio

`GET /api/agenda/servicios/{servicio_id}/disponibilidad` · RF8 · `ADM_CLINICA`, `RECEPCION`, `PROFESIONAL`

Los profesionales que tienen al menos un espacio para ese servicio en el rango, con todos los días del rango; los días
sin espacio vienen con la lista vacía. No usa la caché.

| Parámetro | Tipo | Regla |
|---|---|---|
| `desde` | fecha | Obligatorio |
| `dias` | entero | 1 a 31. Por defecto, 7 |
| `ignorar_cita` | id | Opcional, igual que en RF7 |

**Respuesta 200**

```json
[{ "profesional": { "id": "99578cd7-…", "nombre": "Dra. Laura Méndez", "especialidad": "Medicina general" },
   "dias": [ { "fecha": "2026-11-16", "espacios": ["2026-11-16T14:00:00Z", "2026-11-16T14:15:00Z"] },
             { "fecha": "2026-11-17", "espacios": [] } ] }]
```

**Errores:** 404 si el servicio no existe en tu clínica.

### Reservar una cita

`POST /api/agenda/citas` · RF9 · `ADM_CLINICA`, `RECEPCION`

| Campo | Tipo | Regla |
|---|---|---|
| `paciente_id` | id | De tu clínica |
| `profesional_id` | id | Activo, y debe atender el servicio |
| `servicio_id` | id | Activo |
| `inicio` | instante | Futuro, en minutos exactos, dentro del horario y fuera de los bloqueos |

No se envía `fin`: lo fija la duración del servicio (I4). Enviar `fin` o `clinica_id` es un 422.

```json
{ "paciente_id": "c30fe3c5-…", "profesional_id": "99578cd7-…", "servicio_id": "9f79d973-…",
  "inicio": "2026-11-16T08:00:00-06:00" }
```

**Respuesta 201:** la cita. Las demás rutas de citas responden con esta misma forma.

```json
{ "id": "5b1f…", "paciente_id": "c30fe3c5-…", "profesional_id": "99578cd7-…", "servicio_id": "9f79d973-…",
  "inicio": "2026-11-16T14:00:00Z", "fin": "2026-11-16T14:15:00Z", "estado": "RESERVADA",
  "creada_por": "…", "creada_en": "2026-11-09T19:58:12Z",
  "cancelada_por": null, "cancelada_en": null, "motivo_cancelacion": null, "cita_origen_id": null,
  "paciente": "Ana Solís", "servicio": "Control" }
```

| Error | Cuándo |
|---|---|
| 409 `cita_sin_solape_profesional` | Ese espacio ya fue tomado. Si dos personas reservan a la vez, solo una gana |
| 409 `cita_sin_solape_paciente` | El paciente ya tiene otra cita a esa hora |
| 422 | Paciente, profesional o servicio inexistentes, desactivados o no habilitados; inicio pasado, fuera de horario, en un bloqueo o con segundos |
| 503 | Conflicto transitorio entre transacciones. Repetir |

### Reprogramar una cita

`POST /api/agenda/citas/{cita_id}/reprogramar` · RF10 · `ADM_CLINICA`, `RECEPCION`

No edita la cita: la antigua pasa a `REPROGRAMADA` y se crea otra que apunta a ella con `cita_origen_id`. Conserva el
paciente, el servicio y la duración. Puede cambiar de profesional. Todo ocurre en una sola transacción: si el espacio
nuevo está ocupado, la original queda intacta.

| Campo | Tipo | Regla |
|---|---|---|
| `profesional_id` | id | Puede ser otro |
| `inicio` | instante | Las mismas reglas que al reservar |

**Respuesta 201:** la cita nueva, con `cita_origen_id` igual a la antigua.

| Error | Cuándo |
|---|---|
| 409 | La cita no está `RESERVADA`, o el espacio nuevo está ocupado |
| 422 | El espacio es el mismo que el actual, o no cumple las reglas de una reserva |

### Cancelar una cita

`POST /api/agenda/citas/{cita_id}/cancelar` · RF11 · `ADM_CLINICA`, `RECEPCION`

El espacio queda libre de inmediato (I7). Se guardan quién canceló, cuándo y el motivo.

```json
{ "motivo": "El paciente avisó que no puede asistir" }
```

**Respuesta 200:** la cita con `estado: "CANCELADA"`, `cancelada_por`, `cancelada_en` y `motivo_cancelacion`.

**Errores:** 409 si la cita no está `RESERVADA`. 422 si el motivo tiene menos de 3 caracteres.

### Registrar el desenlace

`POST /api/agenda/citas/{cita_id}/desenlace` · RF12 · `ADM_CLINICA`, `RECEPCION`, `PROFESIONAL`

Atendida o ausente, solo una vez pasada la hora de inicio.

```json
{ "desenlace": "ATENDIDA" }
```

**Respuesta 200:** la cita con el estado nuevo.

| Error | Cuándo |
|---|---|
| 409 | La cita no está `RESERVADA`: una cita solo cambia de estado una vez (RF13) |
| 422 | La cita todavía no empieza, o `desenlace` no es `ATENDIDA` ni `AUSENTE` |

---

## Plataforma

### Dar de alta una clínica

`POST /api/plataforma/clinicas` · RF1 · `ADM_PLATAFORMA`

Crea la clínica y su primer administrador, con una cuenta en Keycloak y una contraseña **temporal**: debe cambiarla al
entrar por primera vez. O se crean las dos cosas, o ninguna.

| Campo | Tipo | Regla |
|---|---|---|
| `nombre` | texto | 3 a 80 caracteres |
| `identificador` | texto | 3 a 40; minúsculas, números y guiones. Único |
| `zona_horaria` | texto | Zona IANA que el motor conozca |
| `admin_nombre` | texto | 3 a 80 caracteres |
| `admin_usuario` | texto | 3 a 40; minúsculas, números, `.`, `_` y `-`. Único en Keycloak |
| `admin_contrasena` | texto | 8 a 128 caracteres. No se guarda en MediCitas: se entrega a Keycloak |

```json
{ "nombre": "Clínica Central", "identificador": "clinica-central", "zona_horaria": "America/Costa_Rica",
  "admin_nombre": "Marta Vargas", "admin_usuario": "central-admin", "admin_contrasena": "temporal-123" }
```

**Respuesta 201**

```json
{ "clinica": { "id": "…", "nombre": "Clínica Central", "identificador": "clinica-central",
               "zona_horaria": "America/Costa_Rica", "creada_en": "2026-11-09T20:10:00Z" },
  "admin": { "id": "…", "nombre": "Marta Vargas", "rol": "ADM_CLINICA", "activo": true } }
```

| Error | Cuándo |
|---|---|
| 409 | El identificador de la clínica o el usuario ya existen |
| 422 | Datos inválidos o zona horaria desconocida |
| 503 | Keycloak no responde. No se creó nada |

### Listar clínicas

`GET /api/plataforma/clinicas` · RF1 · `ADM_PLATAFORMA`

Todas las clínicas, con su número de usuarios activos. No expone ningún dato clínico.

**Respuesta 200**

```json
[{ "id": "fb5ec88a-…", "nombre": "Clínica San Rafael", "identificador": "san-rafael",
   "zona_horaria": "America/Costa_Rica", "creada_en": "2026-11-03T15:00:00Z", "usuarios": 6 }]
```

### Pacientes

RF14 · `ADM_CLINICA` y `RECEPCION` leen y escriben · `PROFESIONAL` solo lee · `ADM_PLATAFORMA` recibe 403

Un paciente es único por `identificacion` **dentro de su clínica**: la misma persona puede ser paciente de dos clínicas.
Abrir la ficha (`GET /{id}`), registrar y actualizar quedan en la bitácora (RF18) dentro de la misma transacción. El
listado no trae teléfono ni correo y por eso no se audita.

| Campo | Tipo | Regla |
|---|---|---|
| `identificacion` | texto | 3 a 30 caracteres. Única en la clínica |
| `nombre` | texto | 3 a 80 caracteres |
| `fecha_nacimiento` | fecha | Entre 1900-01-01 y hoy |
| `telefono` | texto | Opcional. Dígitos, espacios y `-`, mínimo 7 caracteres; puede empezar con `+` |
| `correo` | texto | Opcional. Se guarda en minúsculas |

Enviar `id` o `clinica_id` es un 422.

```json
{ "identificacion": "1-0987-0456", "nombre": "Ana Solís", "fecha_nacimiento": "1990-05-17",
  "telefono": "8888-1234", "correo": "ana@correo.com" }
```

**`POST /api/plataforma/pacientes`** → 201 con la ficha (`id`, los campos de arriba).
**`PUT /api/plataforma/pacientes/{id}`** → 200 con la ficha. Reemplaza todos los campos.
**`GET /api/plataforma/pacientes/{id}`** → 200 con la ficha. Auditado.
**`GET /api/plataforma/pacientes?q=texto`** → 200. Busca en nombre e identificación; trae los primeros 50 por nombre.

```json
{ "total": 1, "pacientes": [{ "id": "…", "nombre": "Ana Solís", "identificacion": "1-0987-0456", "fecha_nacimiento": "1990-05-17" }] }
```

| Error | Cuándo |
|---|---|
| 404 | El paciente no existe en tu clínica (también si es de otra) |
| 409 | Esa identificación ya la tiene otro paciente de la clínica |
| 422 | Datos inválidos o campos que sobran |

---

## Cómo mantener este documento

Quien agregue o cambie una ruta actualiza su sección en el mismo commit, con el formato de las demás. Las lecturas de
agenda (profesionales, horarios, disponibilidad) y los mensajes de error salieron de la API real con la semilla; los demás
ejemplos siguen la forma exacta de los esquemas con valores ilustrativos. Si una respuesta cambia de forma, la fuente de
verdad es `/docs`, y este archivo se corrige.
