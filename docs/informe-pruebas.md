# MediCitas, Etapa 1: informe de pruebas

Qué prueba cubre cuál requisito funcional y cuál invariante, cómo correrlas y qué se midió. Los nombres de las pruebas son
los reales del repositorio: cada fila se puede buscar con `pytest -k <nombre>` o abriendo el archivo indicado.

## 1. Cómo correr las pruebas

Un solo comando corre todas (unitarias e integración de los tres servicios), contra la misma base real del Compose, sin
preparar datos: cada prueba arma los suyos.

```bash
bash pruebas.sh        # Linux, macOS o Git Bash
.\pruebas.ps1          # PowerShell (Windows)
```

| Qué | Comando |
|---|---|
| Un solo servicio | `docker compose --profile pruebas run --rm pruebas-agenda` (o `pruebas-plataforma`, `pruebas-auditoria`) |
| Solo las unitarias, sin base ni Redis | `docker compose --profile pruebas run --rm --no-deps pruebas-agenda python -m pytest tests/unitarias` |
| **La prueba de carrera (I1), con detalle** | `docker compose --profile pruebas run --rm pruebas-agenda python -m pytest tests/test_concurrencia.py -v` |
| Restricciones del esquema, directo en la base | `docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/pruebas/restricciones.sql` |
| Recorrido de una cita contra la API real | `.\recorrido.ps1` |

Resultado de la última corrida completa: **agenda 368, plataforma 314 y auditoría 125 pruebas, todas pasan (807)**. Las
pruebas compartidas (`servicios/pruebas_comunes/`) se copian a cada servicio, así que están incluidas en esas cifras.

## 2. Qué tipos de prueba hay

| Tipo | Qué prueba | Qué necesita | Dónde |
|---|---|---|---|
| **Unitarias** | La lógica propia del código: validaciones, orden de bloqueos, máquina de estados, invalidación de la caché, decisión de permisos y del token | Nada: ni base ni Redis (usan dobles) | `servicios/*/tests/unitarias/`, `servicios/pruebas_comunes/unitarias/` |
| **De integración** | La API contra la pila real: lo que decide el motor (solapes, claves foráneas, triggers), concurrencia, caché con Redis | Postgres con el esquema; las de caché, también Redis | `servicios/*/tests/test_*.py` |
| **De restricciones (SQL)** | Que el **motor** rechace cada operación ilegal con el código de error esperado, sin pasar por la API | Postgres | `db/pruebas/restricciones.sql` |
| **Barrido de aislamiento (I5)** | Cada ruta de cada servicio, atacada desde otra clínica | Postgres | `servicios/pruebas_comunes/aislamiento.py` y `test_aislamiento_i5.py` de cada servicio |
| **Matriz de permisos y token (RF17)** | Cada ruta con cada rol (200/403), y el token con 401, 403 y 503 | Postgres | `servicios/pruebas_comunes/permisos.py` y `test_permisos.py` de cada servicio |
| **Manejo de errores** | Que una entrada mal formada o un recurso inexistente nunca tumbe el servicio | Postgres | `servicios/pruebas_comunes/errores.py` y `test_errores.py` de cada servicio |

Cuál escribir: si lo decide el **código** (un orden, un rechazo, una invalidación), unitaria; si lo decide el **motor** (que
dos reservas simultáneas terminen en un solo `201`), integración, porque un doble no puede reproducir al motor.

## 3. Requisitos funcionales

Las rutas de cada requisito están en [api.md](api.md). Las pruebas de **permisos** (matriz por rol, RF17), de **aislamiento**
(I5) y de **errores** de cada servicio recorren *todas* las rutas, por lo que cubren también cada RF de esta tabla en esos
tres aspectos; aquí se anota lo propio de cada requisito.

### Administración de la plataforma y de la clínica (servicio `plataforma`)

| RF | Qué se prueba | Archivo y pruebas principales |
|---|---|---|
| RF1 Alta de clínica | Crea la clínica y su primer administrador; identificador repetido es 409; si Keycloak cae no queda una clínica a medias | `plataforma/tests/test_alta.py`: `test_crea_la_clinica_y_su_administrador`, `test_identificador_repetido_es_409_y_no_toca_keycloak`, `test_si_keycloak_cae_no_queda_clinica_a_medias` |
| RF2 Usuarios | Alta en la clínica de la sesión (nunca en otra), rol no elevable a plataforma, baja lógica | `plataforma/tests/test_usuarios.py`: `test_alta_crea_usuario_en_la_clinica_de_la_sesion`, `test_alta_no_acepta_clinica_ni_rol_de_plataforma`, `test_alta_con_keycloak_caido_no_deja_usuario`, `test_baja_y_reactivacion`, `test_cambiar_rol` |
| RF3 Catálogo de servicios | Crear, duración válida, nombre repetido es 409, la especialidad debe ser de la clínica | `plataforma/tests/test_catalogo.py`: `test_crear_servicio`, `test_nombre_repetido_es_409`, `test_especialidad_de_otra_clinica_es_422` |
| RF4 Profesionales y servicios habilitados | Registro con servicios, sin repetidos, el usuario debe tener rol PROFESIONAL y estar activo | `plataforma/tests/test_profesionales.py`: `test_registrar_con_servicios`, `test_usuario_sin_rol_de_profesional_o_ajeno_es_422`, `test_usuario_dado_de_baja_es_422` |

### Agenda y disponibilidad (servicio `agenda`)

| RF | Qué se prueba | Archivo y pruebas principales |
|---|---|---|
| RF5 Horario semanal | Varios bloques por día (jornada partida), bloques que no se solapan, validaciones | `agenda/tests/test_horarios.py`: `test_jornada_partida_y_listado_ordenado`, `test_bloques_solapados_los_rechaza_el_motor`; `agenda/tests/unitarias/test_validaciones.py`; en el motor: `db/pruebas/restricciones.sql` (bloque solapado, día 8, fin antes que inicio) |
| RF6 Bloqueos | Crear y quitar un bloqueo, citas en conflicto listadas, no cancela citas por sí solo | `agenda/tests/test_bloqueos.py`: `test_el_bloqueo_lista_los_conflictos_y_no_cancela_nada`, `test_eliminar_bloqueo`; `test_crear_y_quitar_un_bloqueo_invalida` (`test_cache.py`) |
| RF7 Espacios disponibles | Horario, duración del servicio, bloqueos y citas vigentes; lo que RF7 ofrece lo acepta RF9 y lo de al lado no | `agenda/tests/test_disponibilidad.py`, `unitarias/test_disponibilidad_logica.py`, `test_lo_que_RF7_ofrece_lo_acepta_RF9_y_lo_de_al_lado_no_I3` |
| RF8 Disponibilidad por servicio en un rango | Profesionales habilitados para el servicio, en varios días | `agenda/tests/test_disponibilidad.py`: `test_rf8_devuelve_solo_los_profesionales_con_espacio_y_todos_los_dias`, `test_rf8_un_servicio_deshabilitado_para_el_profesional_no_lo_incluye`, `test_rf8_rango_invalido` |
| RF9 Reservar | Concedida, espacio tomado (409), solicitud inválida (422), pasado, fuera de horario, bloqueo, referencias ajenas | `agenda/tests/test_reserva.py`: `test_reserva_concedida`, `test_solape_de_profesional_lo_rechaza_el_motor`, `test_no_se_reserva_en_el_pasado`, `test_solicitudes_mal_formadas`; la carrera: `test_ocho_clientes_compiten_por_el_ultimo_espacio_y_gana_uno_I1` |
| RF10 Reprogramar | Todo o nada: si el espacio nuevo está tomado, la cita original queda intacta; la vieja pasa a REPROGRAMADA y nace otra | `agenda/tests/test_ciclo_de_vida.py`: `test_reprogramar_crea_una_cita_nueva_y_marca_la_antigua`, `test_si_el_espacio_esta_tomado_la_cita_original_queda_intacta`, `test_moverla_15_minutos_no_choca_consigo_misma` |
| RF11 Cancelar | Exige motivo, deja responsable, libera el espacio | `test_cancelar_exige_motivo`, `test_cancelar_deja_motivo_y_responsable_y_libera_el_espacio_I7` |
| RF12 Desenlace | Solo ATENDIDA o AUSENTE y solo una vez pasada la hora de inicio | `test_el_desenlace_no_se_registra_antes_de_la_hora_RF12`, `test_el_desenlace_solo_admite_atendida_o_ausente`, `test_permisos_del_desenlace` |
| RF13 Estados y transiciones | Un estado final no admite ninguna operación, y **el motor también rechaza** una transición que salte la API; dos operaciones simultáneas sobre la misma cita, gana una | `test_un_estado_final_no_admite_ninguna_operacion`, `test_el_motor_tambien_rechaza_una_transicion_que_salte_la_api`, `agenda/tests/unitarias/test_estados.py`, `test_dos_operaciones_sobre_la_misma_cita_gana_una_RF13` (`test_concurrencia.py`) |
| RF20 Agenda del día | Por profesional y de toda la clínica; el profesional ve solo la suya | `agenda/tests/test_dia.py`: `test_clinica_completa_ordenada_por_hora`, `test_filtra_por_profesional`, `test_el_profesional_solo_ve_la_suya`, `test_solo_el_dia_local_de_la_clinica` |

### Pacientes, notas e historial (servicio `plataforma`)

| RF | Qué se prueba | Archivo y pruebas principales |
|---|---|---|
| RF14 Pacientes | Alta y actualización, identificación repetida es 409 solo dentro de la misma clínica, el profesional solo lee | `plataforma/tests/test_pacientes.py`: `test_identificacion_repetida_da_409_pero_en_otra_clinica_se_permite`, `test_profesional_solo_lee` |
| RF15 Nota clínica | Solo sobre una cita ATENDIDA y solo el profesional de esa cita; la de otro profesional o clínica es 404 | `plataforma/tests/test_notas_historial.py`: `test_solo_citas_atendidas_409`, `test_cita_de_otro_profesional_o_clinica_da_404`, `test_profesional_escribe_lee_y_reemplaza_su_nota` |
| RF16 Historial del paciente | Citas con su estado, dentro de la clínica del paciente | `plataforma/tests/test_notas_historial.py`: `test_historial_trae_todas_las_citas_con_estado_de_la_mas_reciente_a_la_mas_antigua`, `test_historial_de_otra_clinica_404` |

### Identidad, bitácora y reportes

| RF | Qué se prueba | Archivo y pruebas principales |
|---|---|---|
| RF17 Autenticación y autorización | **Token:** sin cabecera, otro esquema, basura, otra firma, vencido, otro emisor, `id_token`, sin `sub`, `sub` desconocido y `alg: none` dan 401; usuario dado de baja y rol equivocado, 403; llaves inalcanzables, 503. **Matriz:** cada ruta con cada rol | `servicios/pruebas_comunes/permisos.py` (usada por `test_permisos.py` de cada servicio), `pruebas_comunes/unitarias/test_sesion_token_tenant.py`; extremo a extremo con Keycloak real: `recorrido.ps1` |
| RF18 Bitácora de lecturas y escrituras | Cada lectura y escritura de nota clínica y de contacto de paciente deja su fila, en la misma transacción | `plataforma/tests/test_notas_historial.py`: `test_nota_queda_en_la_bitacora`; `plataforma/tests/unitarias/test_permisos_y_bitacora.py` (cada ruta registra la acción correcta sobre el paciente correcto) |
| RF19 Consulta de la bitácora | Solo el administrador de la clínica; filtros por usuario, paciente y rango de fechas en hora local; nunca la de otra clínica | `auditoria/tests/test_bitacora.py`: `test_filtra_por_usuario`, `test_filtra_por_paciente_por_nombre_o_identificacion`, `test_rango_de_fechas_usa_el_dia_local_e_incluye_ambos_extremos`, `test_no_muestra_la_bitacora_de_otra_clinica` |
| RF21 Citas por estado | Cuenta por estado en un rango, extremos en día local, rango inválido es 422, rango de un año se acepta | `auditoria/tests/test_reportes.py` |

## 4. Invariantes

La columna **Quién lo sostiene** dice si lo impone el motor o la aplicación. Las dos pruebas que más importan de cada
invariante están en negrita.

| Invariante | Quién lo sostiene | Pruebas |
|---|---|---|
| **I1** Un profesional nunca tiene dos citas vigentes solapadas | **El motor:** `EXCLUDE USING gist` (`23P01`, la API responde 409) | **`test_ocho_clientes_compiten_por_el_ultimo_espacio_y_gana_uno_I1`** (la prueba de carrera: 8 clientes al mismo espacio, **exactamente una reserva concedida**); **`restricciones.sql`** (solape total y parcial; una cita ATENDIDA o AUSENTE también ocupa el espacio); `test_solape_de_profesional_lo_rechaza_el_motor` |
| **I2** Un paciente nunca tiene dos citas vigentes solapadas en la clínica | **El motor:** segunda exclusión | **`test_un_paciente_no_puede_estar_en_dos_consultas_a_la_vez_I2`**; **`restricciones.sql`** (mismo paciente, otro profesional); `test_solape_de_paciente_con_otro_profesional` |
| **I3** Toda cita vigente cae en el horario y fuera de los bloqueos | **La aplicación**, no el motor: `cabe_en_horario` más `FOR NO KEY UPDATE` sobre el profesional (ver límites) | **`test_un_bloqueo_y_una_reserva_simultaneos_nunca_dejan_una_cita_dentro_del_bloqueo_sin_avisar_I3`** y **`test_quitar_un_horario_y_una_reserva_simultaneos_nunca_dejan_una_cita_fuera_de_horario_sin_avisar_I3`** (concurrencia); `test_fuera_del_horario_I3`, `test_bloqueo_I3`, `test_una_cita_que_cruza_la_medianoche_no_cabe_aunque_las_horas_lo_parezcan_I3`, `test_reprogramar_respeta_horario_y_bloqueos_I3` |
| **I4** La duración la determina el servicio y nada la altera | **El motor:** `cita.fin` como instantánea más trigger (migración 007) | **`test_el_motor_rechaza_editar_la_duracion_I4`**; **`restricciones.sql`** (el inicio y el fin no se editan); `test_la_duracion_se_conserva_aunque_el_servicio_haya_cambiado_I4`, `test_la_duracion_la_decide_el_servicio_y_no_se_puede_enviar_fin_ni_clinica` |
| **I5** Ningún dato de una clínica es accesible desde otra | **El motor** (claves foráneas compuestas) **y la aplicación** (toda consulta filtra por la clínica de la sesión) | **El barrido:** `test_ninguna_ruta_deja_ver_ni_tocar_otra_clinica_I5` en los tres servicios, con ids ajenos, mezclados, `clinica_id` inyectado y la cabecera `X-Clinica-Id`, más un "canario" y una huella `md5` de las tablas de la víctima; `test_todas_las_rutas_estan_en_el_barrido` falla si una ruta nueva no se agrega; **`restricciones.sql`** (cita de A con paciente o profesional de B, `23503`) |
| **I6** La bitácora no se modifica ni se borra desde la aplicación | **El motor, con dos barreras:** privilegios (migración 011) y trigger (migración 010) | **`test_el_motor_rechaza_modificar_o_borrar_la_bitacora_I6`**; **`test_ningun_rol_de_la_aplicacion_puede_modificar_ni_borrar_la_bitacora_I6`**; **`restricciones.sql`** (`UPDATE`, `DELETE` y `TRUNCATE` fallan con `42501`); `test_la_bitacora_sigue_admitiendo_filas_nuevas_I6` |
| **I7** Cancelar o reprogramar libera el espacio de inmediato | **La aplicación**, con el estado como filtro de la exclusión | **`test_cancelar_libera_el_espacio_I7`**; **`test_reprogramar_libera_el_espacio_viejo_y_ocupa_el_nuevo_I7`**; `test_la_reserva_desaparece_de_la_disponibilidad_I7`, `test_cancelar_devuelve_el_espacio_de_inmediato` |
| **I8** La disponibilidad nunca contradice a la base, aunque venga de la caché | **La aplicación:** clave con versión por profesional, que sube después del `COMMIT` | **`test_i8_reservar_y_volver_a_consultar_muestra_el_espacio_tomado`** (reserva y vuelve a consultar, con Redis real); **`test_una_copia_tardia_de_antes_de_invalidar_nadie_la_lee`**; `test_reprogramar_a_otro_profesional_invalida_las_dos_agendas`, `test_el_commit_ocurre_antes_de_enviar_la_respuesta`, `agenda/tests/unitarias/test_cache_logica.py` |

### Transacciones y concurrencia

Además de la carrera de I1, estas pruebas respaldan las decisiones de aislamiento (ver [diseno-datos.md](diseno-datos.md), sección 7):

| Qué | Prueba |
|---|---|
| El nivel de aislamiento activo es READ COMMITTED, fijado de forma explícita | `test_el_nivel_de_aislamiento_activo_es_read_committed` |
| Un deadlock real (dos transacciones que se piden los bloqueos al revés) se reintenta y se resuelve | `test_deadlock_real_dos_transacciones_que_se_piden_los_bloqueos_al_reves`, `test_reintento_tras_un_deadlock`, `test_si_el_deadlock_persiste_el_error_sube`, `test_otros_errores_no_se_reintentan` |
| Las tareas posteriores (como invalidar la caché) corren después del commit y solo si hubo commit | `test_las_tareas_corren_tras_el_commit_y_solo_si_hubo_commit` |
| Redis caído o colgado no tumba la API ni la retrasa más que el límite | `test_si_redis_no_responde_todo_sigue_funcionando_y_sin_demora`, `test_redis_colgado_no_retrasa_mas_que_el_limite` |

## 5. Qué se midió

Los índices se justifican con el plan de ejecución y la caché con una comparación antes y después. Medianas en una sola
computadora, con un ruido de hasta ±30 % entre corridas; las pruebas de carga corresponden a la Etapa 2.

**Caché de RF7** (una solicitud contra la API real, con 83 mil citas y 50 mil bloqueos sintéticos,
[`medir_cache.py`](../servicios/agenda/tests/medir_cache.py)):

| Una solicitud de RF7 | Sin caché | Con la copia en Redis | Con caché, sin copia |
|---|---|---|---|
| Con los índices (el estado actual) | 9,6 ms | 7,4 ms | 11,6 ms |
| Sin esos índices | 17,5 ms | 8,2 ms | 20 ms |

Con los índices, una copia ahorra unos 2 ms; sin ellos, más del doble. **Índices** (antes → después): bloqueos en RF7,
4,39 → ~1,5 ms; agenda del día de la clínica (RF20), 126 → ~2,2 ms; reserva (¿cae en un bloqueo?), 2,66 → ~0,1 ms. El detalle y
las decisiones están en [diseno-datos.md](diseno-datos.md), secciones 8 y 9.

## 6. Qué no se prueba, y por qué

- **I3 no la impone el motor:** el motor no impide por sí solo una cita fuera de horario insertada por un camino que no tome el
  bloqueo del profesional. Se prueba por la API, incluida la concurrencia, pero no hay una prueba que lo intente "por debajo".
- **I6 no se defiende de un dueño de la base:** quien sea dueño de la tabla podría desactivar el trigger. Las pruebas
  verifican las dos barreras contra la aplicación; los servicios no se conectan como dueño.
- **El frontend no se prueba:** es una demostración con datos en memoria que no llama a las APIs.
- **Keycloak real:** las pruebas automáticas usan tokens firmados con una llave propia (así se prueban vencido, otra firma,
  `alg: none`). El flujo con el Keycloak real lo ejercita `recorrido.ps1`.
- **Pruebas de carga y de rendimiento sostenido:** corresponden a la Etapa 2. Solo hay las mediciones de la sección 5.
- **Historial del paciente (RF16) y bitácora (RF19) sin índices medidos con volumen:** se prueban por corrección, no por
  rendimiento.
