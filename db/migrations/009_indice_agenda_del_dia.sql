-- 009: índice de la agenda del día (RF20) y del conteo de citas por estado (RF21).
--
-- Las dos consultas filtran por `clinica_id` y por un rango de `inicio`:
--     WHERE c.clinica_id = … AND c.inicio >= <medianoche local> AND c.inicio < <medianoche siguiente>
-- Ningún índice de `cita` empieza por esas columnas (el GiST de I1 y el parcial de 008 son por profesional), así que
-- el motor leía la tabla entera: en un SaaS, las citas de TODAS las clínicas y de todo el historial.
-- Medido con db/pruebas/historial_sintetico.sql (unas 83 mil citas de 2 000 clínicas): la agenda de un día de una
-- clínica, de 126 ms a 2,2 ms.
--
-- Límite conocido (el mismo de 008): CREATE INDEX bloquea las escrituras de `cita` mientras se construye. Con una tabla
-- grande en producción se usaría CREATE INDEX CONCURRENTLY, fuera de transacción.

CREATE INDEX cita_por_clinica_e_inicio ON cita (clinica_id, inicio);
