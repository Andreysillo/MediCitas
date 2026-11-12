# Servicio de agenda

Horarios, bloqueos, disponibilidad y el ciclo de vida de la cita. Documentación interactiva de las
rutas: http://localhost:8080/api/agenda/docs. Pruebas: ver [../README.md](../README.md#pruebas).

## Rutas

| Ruta | RF | Quién |
|---|---|---|
| `GET /profesionales` | RF5 | administrador de clínica (todos), profesional (solo él) |
| `GET·POST /profesionales/{id}/horarios`, `DELETE /horarios/{id}` | RF5 | ídem |
| `GET·POST /profesionales/{id}/bloqueos`, `DELETE /bloqueos/{id}` | RF6 | ídem |
| `GET /profesionales/{id}/disponibilidad?servicio_id=&fecha=` | RF7 | administrador, recepción, profesional |
| `GET /servicios/{id}/disponibilidad?desde=&dias=` | RF8 | ídem |
| `POST /citas` | RF9 | administrador de clínica, recepción |
| `POST /citas/{id}/reprogramar` | RF10 | ídem |
| `POST /citas/{id}/cancelar` | RF11 | ídem |
| `POST /citas/{id}/desenlace` | RF12 | administrador de clínica, recepción, profesional |

## Archivos

```
app/
  main.py            registra los routers
  horarios.py        RF5          bloqueos.py     RF6          disponibilidad.py   RF7 y RF8 (rutas)
  citas.py           RF9 a RF13 (rutas y máquina de estados)
  reserva.py         las reglas de un espacio, compartidas por reservar y reprogramar
  espacios.py        la consulta SQL que calcula los espacios libres (la más ejecutada del sistema; índices en db/README.md)
  cache.py           caché de RF7 en Redis y su invalidación (I8)
  conflictos.py      citas que un bloqueo o un cambio de horario deja sin cubrir
  permisos.py        quién puede tocar los horarios de quién + el bloqueo de fila sobre el profesional
  esquemas.py        forma de lo que entra y sale (validación y /docs)
tests/               contra la base real, cada prueba se deshace con ROLLBACK
```

## Cómo se calcula la disponibilidad

`espacios.py`, en una sola consulta SQL: (1) los bloques del horario semanal de cada profesional, convertidos a
instantes reales de cada día; (2) dentro de cada bloque, un inicio posible cada 15 minutos mientras la cita entera
quepa; (3) se descarta lo que se traslapa con una cita vigente o con un bloqueo, y lo que ya pasó.

- Cada bloque se calcula por separado: una cita no puede cruzar el almuerzo de una jornada partida.
- `ignorar_cita` libera el espacio de la cita que se está reprogramando (RF10), para que no se estorbe a sí misma.
- La disponibilidad dice qué espacios están libres **ahora**; quien reserva (T12) vuelve a comprobarlo dentro de su
  transacción, porque entre la consulta y la reserva otra persona pudo tomarlo. La palabra final la tiene la
  restricción de exclusión del motor (I1).

## Caché de disponibilidad (RF7, I8)

Redis guarda copias de la respuesta de RF7. La verdad sigue en PostgreSQL: Redis se puede vaciar en cualquier momento sin
perder nada, y por eso corre sin disco. Un respaldo reviviría copias que quizá ya son falsas.

La clave lleva todo lo que cambia la respuesta y nada más:

```
disp:{clinica}:{profesional}:v{version}:{servicio}:{duracion}:{fecha}
```

Cada consulta de RF7 hace esto, en este orden (`app/disponibilidad.py` y `app/cache.py`):

1. Valida en la base el servicio y el profesional, con la clínica de la sesión (I5).
2. Lee la versión de la agenda del profesional.
3. Busca la copia. Si está, quita las horas ya pasadas y responde.
4. Si no está, calcula en la base y guarda la copia por 5 minutos.

**Invalidar es subir la versión del profesional.** Las copias anteriores quedan bajo claves que nadie vuelve a buscar, y el
TTL las borra. Con un solo `INCR` se invalidan todas las fechas y todos los servicios de esa agenda.

| Operación | ¿Sube la versión? | Por qué |
|---|---|---|
| Reservar, cancelar | Sí | Cambia qué espacios están libres |
| Reprogramar | Sí, de los dos profesionales si son distintos | Se libera un espacio y se ocupa otro |
| Crear o quitar un horario o un bloqueo | Sí | Cambia qué espacios existen |
| Desenlace | No | ATENDIDA y AUSENTE siguen ocupando su espacio |

Lo que quedó decidido y por qué:

| Decisión | Razón |
|---|---|
| Invalidar después del `COMMIT` y antes de la respuesta | Antes del commit, una consulta podría volver a guardar la agenda sin ver el cambio. Antes de la respuesta, para que quien reservó ya no vea su espacio libre. Las rutas lo piden con `cache.invalidar_tras_commit`. |
| Leer la versión antes de calcular | Si una consulta guarda tarde una copia vieja, queda con el número anterior y nadie la encuentra. |
| Validar antes de leer la caché | Nadie de otra clínica llega a una copia, y un profesional desactivado deja de aparecer al instante. Cuesta dos lecturas pequeñas en la base por consulta. |
| La duración va en la clave | `plataforma` puede editar un servicio sin tocar Redis: con otra duración, la clave es otra. |
| Filtrar el pasado al leer | El tiempo no dispara ninguna invalidación, pero solo quita espacios. |
| TTL de 5 minutos | Es una red de seguridad, no lo que cumple I8: limita cuánto dura un error si falla un `INCR` y limpia las versiones viejas. |
| Sin caché en RF8, `ignorar_cita` y la reserva | RF8 mezcla varios profesionales y rangos. `ignorar_cita` muestra libre un espacio ocupado: guardada, se la daría a todos. La reserva necesita la verdad, no una copia. |
| Límite de 250 ms por acceso a Redis | Con el contenedor apagado cada solicitud tardaba unos 4 s, porque el tiempo del socket no cubre la resolución del nombre. Con el límite, unos 280 ms (medido). |
| Si Redis falla, se sigue sin él | Las consultas salen de la base y las escrituras responden normal, con un aviso en el log. Un 503 tras el commit haría que el cliente repita algo que sí ocurrió. |

Qué incoherencia queda, y cuánto dura:

- **Entre el `COMMIT` y el `INCR`:** unos milisegundos en que otro cliente aún lee la copia anterior. Si intenta reservar ese espacio, el motor responde 409 (I1). Quien reservó nunca lo ve, porque la respuesta sale después del `INCR`.
- **Si falla el `INCR` y Redis sigue con sus datos** (por ejemplo, un corte de red): la copia vieja dura como mucho 5 minutos. Si Redis se reinició, no pasa nada: quedó vacío.
- **Si cambia la zona horaria de una clínica:** lo edita `plataforma`, no va en la clave y no invalida. También dura como mucho 5 minutos.

Toda ruta nueva que cambie citas vigentes, horarios o bloqueos debe llamar a `cache.invalidar_tras_commit`. Las pruebas están
en `tests/test_cache.py`, con Redis real y commits de verdad.

## Cómo se reserva (RF9)

Una sola transacción, en `READ COMMITTED`, con este orden (detalle y porqué en [app/reserva.py](app/reserva.py)):

1. Bloquear la fila del **profesional** y luego la del **paciente** (`FOR NO KEY UPDATE`, siempre en ese orden).
2. Validar: existen en la clínica de la sesión (I5), servicio y profesional activos, el profesional atiende el servicio (RF4).
3. Calcular `fin` con la duración del servicio (I4) y comprobar que cabe en el horario y no cae en un bloqueo (I3).
4. Insertar. Si el espacio o el paciente ya están ocupados, **el motor rechaza** (I1, I2) y la API responde 409.
5. `COMMIT`, invalidar la caché y solo entonces la respuesta.

Lo que quedó decidido y por qué:

| Decisión | Razón |
|---|---|
| `READ COMMITTED` (explícito en el pool) | El paso 3 lee horario y bloqueos *después* de esperar el bloqueo del paso 1; cada sentencia debe ver lo que otros confirmaron mientras tanto. Con `REPEATABLE READ` la foto se tomaría antes de esperar y no vería un bloqueo de agenda confirmado en medio. |
| Las colisiones las decide el motor, no un `SELECT` previo | Entre revisar y insertar, otra persona puede tomar el espacio. La restricción de exclusión es atómica. |
| Bloqueo exclusivo por profesional (y paciente) | Sin él, dos inserciones que chocan se esperaban entre sí y Postgres abortaba una con *deadlock* (medido: 8 clientes, varios fallaban). Con él, la segunda espera *antes* de insertar y recibe un 409 limpio. |
| Reintento ante `40P01` (hasta 3 veces) | Red de seguridad por si algún camino futuro produce un deadlock; hoy no debería ocurrir en la reserva. |
| `COMMIT` antes de la respuesta (`scope="function"`) | Con el valor por defecto de FastAPI el 201 salía antes del commit (medido), y quien consultara justo después no vería su reserva. |
| `lock_timeout` de 5 s | Mejor un 503 que una solicitud colgada si algo retiene un bloqueo de más. |

Las pruebas de `tests/test_concurrencia.py` lo demuestran con un servidor real y datos confirmados: 8 clientes disputan el
mismo espacio durante 12 rondas y siempre hay exactamente un 201 y siete 409; un paciente no puede estar en dos consultas a
la vez; y un bloqueo creado a la vez que una reserva nunca deja una cita dentro del bloqueo sin avisar (ver abajo).

## Ciclo de vida de la cita (RF10 a RF13)

Una cita nace RESERVADA y termina en uno de cuatro estados finales, de los que ya no sale:

```
              ┌─► ATENDIDA       el paciente vino       (solo después de la hora de inicio)
              ├─► AUSENTE        no se presentó         (solo después de la hora de inicio)
RESERVADA ────┤
              ├─► CANCELADA      queda motivo y responsable; libera el espacio
              └─► REPROGRAMADA   libera el espacio y nace otra cita RESERVADA que apunta a ésta
```

**Una cita no se edita.** Reprogramar no le cambia la hora a la fila: la marca REPROGRAMADA y crea otra con `cita_origen_id`. Es
como tachar una línea en la agenda y escribir otra con una flecha: el historial conserva qué pasó. La nueva cita mantiene el
paciente, el servicio y la duración de la anterior (I4), aunque el servicio haya cambiado de duración después.

**Reprogramar es todo o nada.** Los dos cambios van en una transacción. Si el espacio nuevo ya está tomado (409), la cita
original queda RESERVADA, como si nada. Nadie ve nunca la cita duplicada ni los dos espacios ocupados. Primero se libera el
espacio viejo y después se inserta el nuevo: si no, mover una cita 15 minutos chocaría consigo misma.

**Dos barreras para la máquina de estados.** La API rechaza una transición no permitida con 409 y un mensaje claro
(`exigir_transicion` en `citas.py`). Además, un trigger del motor (migración 007) impide modificar una cita que ya no está
RESERVADA, por si algún camino se salta la API.

**Dos operaciones a la vez sobre la misma cita** pasan de una en una, gracias al bloqueo de fila: la segunda lee el estado que
dejó la primera y recibe 409. El orden de bloqueos es siempre profesional, paciente, cita.

**El desenlace lo registra cualquier profesional de la clínica**, no solo el de la cita: la matriz dice "sí", sin el "solo los
propios" de otras filas, y no se puede reducir.

## Reservar y bloquear a la vez (I3)

**El problema.** La doctora se va de vacaciones el miércoles de 10 a 12. Dos cosas ocurren en el mismo instante:

1. La directora crea el bloqueo. El sistema busca las citas que ya existen en ese rango para avisarle a recepción cuáles
   reprogramar. Todavía no hay ninguna, así que la lista sale vacía.
2. Recepción reserva una cita a las 10:30. La reserva comprueba si hay bloqueos y no ve ninguno, porque el bloqueo aún no
   se había guardado.

Las dos operaciones terminan bien, y queda **una cita dentro de las vacaciones que no aparece en ninguna lista**: nadie sabe
que hay que reprogramarla. El paciente llega y la doctora no está. Esto es lo que I3 prohíbe.

**La solución.** Las dos operaciones toman el mismo turno sobre la fila de la doctora, así que una pasa primero y la otra ya
ve lo que hizo la primera. Solo hay dos desenlaces posibles, y los dos son correctos:

| Quién llega primero | La reserva recibe | El bloqueo |
|---|---|---|
| La reserva | **201**. La cita queda guardada como cualquier RESERVADA | Se crea y **la incluye en su lista de `conflictos`**, para que recepción la reprograme (RF6) |
| El bloqueo | **422**: "el profesional tiene un bloqueo de agenda en ese horario". No se guarda nada | Se crea con la lista vacía |

**"Conflictos" no es un estado de la cita.** Es una lista que devuelve el bloqueo (al crearlo y al consultarlo) con las citas
reservadas que ya estaban dentro de su rango. Sirve para que recepción la lea y decida qué hacer con cada una:
reprogramarla o cancelarla. Mientras tanto las citas siguen en estado RESERVADA: un bloqueo nunca cancela nada por su cuenta.

## Dos recepcionistas, un mismo espacio (I1)

Ana y Luis envían su solicitud al mismo tiempo para el mismo espacio de la misma doctora. Las dos llegan al servidor y
ninguna es rechazada de entrada. Cada una toma el turno de la doctora, una a la vez:

- La que lo toma primero guarda su cita, confirma, y recibe **201**.
- La otra espera su turno unos milisegundos. Cuando le toca, la cita de la primera ya está confirmada, el motor se lo dice
  con la restricción de exclusión y recibe **409** ("Ese espacio ya fue tomado").

Lo que tarda un poco más es la **solicitud** de quien recibe el 409 (espera su turno en el servidor), no la página: el navegador solo espera la respuesta. El sistema nunca guarda las dos. El paciente no interviene:
solo la recepcionista ve el resultado, y puede ofrecerle otro espacio.
