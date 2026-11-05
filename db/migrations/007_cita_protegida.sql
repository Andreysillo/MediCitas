-- 007: segunda barrera de la máquina de estados (RF13) y de la duración de la cita (I4).
--
-- La API ya rechaza las transiciones no permitidas con un mensaje claro (409). Este trigger es para lo que no pase por
-- ahí: un error en el código, otro servicio o alguien en una consola SQL.
--   - Los cuatro estados finales no admiten salida: una cita que no está RESERVADA ya no se modifica.
--   - Una cita no se edita: para cambiarle el horario se reprograma (RF10), que crea otra. Por eso sus datos de
--     identidad nunca cambian, y `fin` tampoco (I4).
-- Los errores salen como check_violation (23514) con el nombre de la "restricción", igual que un CHECK.

CREATE FUNCTION cita_proteger() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.estado <> 'RESERVADA' THEN
        RAISE EXCEPTION 'Una cita en estado % no admite cambios', OLD.estado
            USING ERRCODE = 'check_violation', CONSTRAINT = 'cita_transicion_permitida';
    END IF;

    IF (NEW.clinica_id, NEW.paciente_id, NEW.profesional_id, NEW.servicio_id, NEW.inicio, NEW.fin,
        NEW.creada_por, NEW.creada_en, NEW.cita_origen_id)
       IS DISTINCT FROM
       (OLD.clinica_id, OLD.paciente_id, OLD.profesional_id, OLD.servicio_id, OLD.inicio, OLD.fin,
        OLD.creada_por, OLD.creada_en, OLD.cita_origen_id) THEN
        RAISE EXCEPTION 'Los datos de una cita no se editan: se reprograma'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'cita_datos_inmutables';
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER cita_protegida BEFORE UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION cita_proteger();
