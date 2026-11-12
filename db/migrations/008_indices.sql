-- 008: índices para las consultas más usadas de la agenda (T15).
--
-- Medido con db/pruebas/historial_sintetico.sql (unas 83 mil citas y 50 mil bloqueos de 2 000 clínicas) y
-- servicios/agenda/tests/medir_consultas.py. Antes y después, con el detalle, en db/README.md («Índices»).
--
-- Lo que NO se agrega, a propósito: RF7 y RF8 buscan citas con
--     profesional_id = … AND tstzrange(inicio, fin, '[)') && … AND estado IN ('RESERVADA','ATENDIDA','AUSENTE')
-- y eso ya lo sirve el índice GiST que el motor creó para la restricción de I1 (cita_sin_solape_profesional, en 004):
-- misma expresión y mismo predicado. Otro índice sobre esas columnas sería redundante, y cada índice extra hace más
-- lentas las reservas. Con pocas filas el motor prefiere leer la tabla entera, y es la decisión correcta.
--
-- Límite conocido: CREATE INDEX bloquea las escrituras de la tabla mientras se construye, porque aplicar.sh corre cada archivo
-- en una transacción. Con una tabla grande en producción se usaría CREATE INDEX CONCURRENTLY, fuera de transacción.

-- Bloqueos de agenda por profesional y rango. Sin él, cada consulta de RF7 y RF8, cada reserva (RF9) y cada listado
-- de bloqueos (RF6) leen la tabla entera, que en un SaaS guarda los bloqueos de TODAS las clínicas y no deja de crecer.
-- La expresión es la misma que usan esas consultas, por eso es GiST: el operador && de rangos no lo sirve un B-tree.
-- Medido: RF7 de 4,4 a 1,5 ms; la comprobación de la reserva y el listado de bloqueos, de unos 3 ms a 0,1 ms. RF8 además
-- necesitó un cambio en la consulta (servicios/agenda/app/espacios.py): de 25 a 6 ms.
CREATE INDEX bloqueo_por_profesional_y_rango ON bloqueo_agenda
    USING gist (profesional_id, tstzrange(inicio, fin, '[)'));

-- Citas RESERVADAS de un profesional que todavía no terminan. Las piden la lista de conflictos al crear un bloqueo o
-- quitar un horario (RF5, RF6) y la baja de un usuario en plataforma (RF2). Sin él, el motor recorre TODAS las citas
-- vigentes del profesional, historial incluido (medido: 6 867 entradas para devolver 86), y eso crece cada día.
-- Es parcial: una cita deja de ser RESERVADA al atenderse, marcarse ausente, cancelarse o reprogramarse, así que el
-- índice solo guarda la agenda pendiente y no crece con el historial.
CREATE INDEX cita_reservadas_por_profesional ON cita (profesional_id, fin)
    WHERE estado = 'RESERVADA';
