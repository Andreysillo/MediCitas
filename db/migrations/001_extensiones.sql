-- 001: lo que el resto del esquema necesita antes de crear tablas.

-- btree_gist permite combinar igualdad (profesional_id WITH =) y solape de rangos (&&) en un mismo
-- índice GiST. Es lo que hace posible la restricción de exclusión de I1 e I2 (migración 004).
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- PostgreSQL trae rangos para fechas y enteros, pero no para horas del día. Los bloques del horario
-- semanal (08:00 a 12:00) son un rango de `time`, y necesitamos compararlos con && para que un
-- profesional no tenga dos bloques solapados el mismo día (migración 003).
CREATE TYPE timerange AS RANGE (subtype = time);
