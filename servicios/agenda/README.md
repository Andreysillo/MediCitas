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
  espacios.py        la consulta SQL que calcula los espacios libres (la más ejecutada del sistema)
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

## Cómo se reserva (RF9)

Una sola transacción, en `READ COMMITTED`, con este orden (detalle y porqué en [app/reserva.py](app/reserva.py)):

1. Bloquear la fila del **profesional** y luego la del **paciente** (`FOR NO KEY UPDATE`, siempre en ese orden).
2. Validar: existen en la clínica de la sesión (I5), servicio y profesional activos, el profesional atiende el servicio (RF4).
3. Calcular `fin` con la duración del servicio (I4) y comprobar que cabe en el horario y no cae en un bloqueo (I3).
4. Insertar. Si el espacio o el paciente ya están ocupados, **el motor rechaza** (I1, I2) y la API responde 409.
5. `COMMIT` y solo entonces la respuesta.

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
