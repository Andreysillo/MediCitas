-- 010: la bitácora solo admite filas nuevas (I6), impuesto por el motor.
--
-- 005 creó la tabla y dejó esto pendiente. Hay dos barreras, y se necesitan las dos:
--   1. PRIVILEGIOS: el rol con el que se conectan los servicios no debe tener UPDATE, DELETE ni TRUNCATE sobre la tabla.
--      Eso lo hace la migración de roles de base de datos (T19, Persona B); NO está en esta. Por sí sola no basta: un
--      privilegio revocado no detiene al DUEÑO de la tabla ni a un superusuario, y hoy los servicios se conectan como tales.
--   2. ESTE TRIGGER: rechaza el cambio sea quien sea, dueño y superusuario incluidos. Es la barrera que ya vale hoy.
-- Lo que ningún trigger evita: quien sea dueño puede desactivarlo con ALTER TABLE … DISABLE TRIGGER, o borrar la tabla.
-- Es DDL, no una operación de la aplicación, y por eso la segunda barrera (que la aplicación no sea dueña) es la que lo cierra.
--
-- Sale como insufficient_privilege (42501), el mismo código que daría un privilegio revocado: quien llame a la base no
-- distingue cuál de las dos barreras lo frenó.

CREATE FUNCTION bitacora_solo_agregar() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'La bitácora solo admite filas nuevas (I6): % no está permitido', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END $$;

-- Una fila a la vez: cada UPDATE o DELETE de una fila de la bitácora.
CREATE TRIGGER bitacora_sin_cambios BEFORE UPDATE OR DELETE ON registro_auditoria
    FOR EACH ROW EXECUTE FUNCTION bitacora_solo_agregar();

-- TRUNCATE no dispara los triggers por fila: necesita el suyo, por sentencia. Se dispara también cuando la tabla se vacía
-- como consecuencia de `TRUNCATE … CASCADE` sobre una tabla a la que apunta (paciente, usuario).
CREATE TRIGGER bitacora_sin_truncate BEFORE TRUNCATE ON registro_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION bitacora_solo_agregar();
