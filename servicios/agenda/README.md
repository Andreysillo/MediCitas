# Servicio de agenda

Horarios, bloqueos, disponibilidad y (próximamente) el ciclo de vida de la cita. Documentación interactiva de las
rutas: http://localhost:8080/api/agenda/docs. Pruebas: ver [../README.md](../README.md#pruebas).

## Rutas

| Ruta | RF | Quién |
|---|---|---|
| `GET /profesionales` | RF5 | administrador de clínica (todos), profesional (solo él) |
| `GET·POST /profesionales/{id}/horarios`, `DELETE /horarios/{id}` | RF5 | ídem |
| `GET·POST /profesionales/{id}/bloqueos`, `DELETE /bloqueos/{id}` | RF6 | ídem |
| `GET /profesionales/{id}/disponibilidad?servicio_id=&fecha=` | RF7 | administrador, recepción, profesional |
| `GET /servicios/{id}/disponibilidad?desde=&dias=` | RF8 | ídem |

## Archivos

```
app/
  main.py            registra los routers
  horarios.py        RF5          bloqueos.py     RF6          disponibilidad.py   RF7 y RF8 (rutas)
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
