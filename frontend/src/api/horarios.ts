import { diaSemanaIso, fechaLocal, minutosHora } from "../fechas";
import { instanteEn } from "./disponibilidad";
import { seSolapan, type BloqueoAgenda, type Cita, type HorarioAtencion, type Instante, type Rol } from "./dominio";
import { ApiError, citaVista, db, nombreUsuario, nuevoId, red, sesionConRol, type CitaVista } from "./nucleo";

// Horario semanal (RF5) y bloqueos de agenda (RF6) de cada profesional.
// Matriz de permisos: el administrador de clínica gestiona los de todos; el profesional, solo los suyos.

const ROLES_QUE_GESTIONAN: readonly Rol[] = ["ADM_CLINICA", "PROFESIONAL"];

export type ProfesionalGestionable = { id: string; nombre: string; especialidad: string };

/** Profesionales cuyo horario puede gestionar quien consulta: todos los de la clínica, o solo él mismo. */
export async function profesionalesGestionables(): Promise<ProfesionalGestionable[]> {
  const { usuario, clinica } = sesionConRol(ROLES_QUE_GESTIONAN, "Tu rol no gestiona horarios ni bloqueos");
  return red(
    db.profesionales
      .filter((p) => p.clinica_id === clinica.id && p.activo && (usuario.rol !== "PROFESIONAL" || p.usuario_id === usuario.id))
      .map((p) => ({
        id: p.id,
        nombre: nombreUsuario(p.usuario_id),
        especialidad: db.especialidades.find((e) => e.id === p.especialidad_id)?.nombre ?? "—",
      })),
  );
}

function profesionalAccesible(profesionalId: string) {
  const { usuario, clinica } = sesionConRol(ROLES_QUE_GESTIONAN, "Tu rol no gestiona horarios ni bloqueos");
  const prof = db.profesionales.find((p) => p.id === profesionalId && p.clinica_id === clinica.id);
  // Un profesional solo toca lo suyo: lo de otro (o de otra clínica) responde como si no existiera.
  if (!prof || (usuario.rol === "PROFESIONAL" && prof.usuario_id !== usuario.id)) throw new ApiError(404, "Profesional no encontrado");
  return prof;
}

// ---------- Conflictos ----------

// Citas reservadas que todavía no terminaron. Las atendidas, ausentes y pasadas no se tocan.
const reservadasFuturas = (profesionalId: string) =>
  db.citas.filter((c) => c.profesional_id === profesionalId && c.estado === "RESERVADA" && Date.parse(c.fin) > Date.now());

/** RF6: un bloqueo no cancela citas; las que caen dentro se listan para que recepción las reprograme. */
const conflictosDeBloqueo = (b: BloqueoAgenda): CitaVista[] =>
  reservadasFuturas(b.profesional_id)
    .filter((c) => seSolapan(Date.parse(b.inicio), Date.parse(b.fin), Date.parse(c.inicio), Date.parse(c.fin)))
    .map(citaVista);

/** I3: tras quitar un bloque del horario, las reservas que quedaron fuera de toda atención también se listan. */
const citasFueraDeHorario = (profesionalId: string): CitaVista[] =>
  reservadasFuturas(profesionalId)
    .filter((c: Cita) => {
      const ini = Date.parse(c.inicio);
      const fin = Date.parse(c.fin);
      const fecha = fechaLocal(new Date(ini));
      return !db.horarios.some(
        (h) =>
          h.profesional_id === profesionalId &&
          h.dia_semana === diaSemanaIso(fecha) &&
          ini >= instanteEn(fecha, h.hora_inicio) &&
          fin <= instanteEn(fecha, h.hora_fin),
      );
    })
    .map(citaVista);

// ---------- Horario semanal (RF5) ----------

export type NuevoHorario = Pick<HorarioAtencion, "dia_semana" | "hora_inicio" | "hora_fin">;

const HORA = /^([01]\d|2[0-3]):[0-5]\d$/;

export async function listarHorarios(profesionalId: string): Promise<HorarioAtencion[]> {
  profesionalAccesible(profesionalId);
  return red(
    db.horarios
      .filter((h) => h.profesional_id === profesionalId)
      .sort((a, b) => a.dia_semana - b.dia_semana || a.hora_inicio.localeCompare(b.hora_inicio)),
  );
}

/** Agrega un bloque semanal. Un mismo día puede tener varios (jornada partida), pero no solapados. */
export async function crearHorario(profesionalId: string, nuevo: NuevoHorario): Promise<HorarioAtencion> {
  const prof = profesionalAccesible(profesionalId);
  if (!Number.isInteger(nuevo.dia_semana) || nuevo.dia_semana < 1 || nuevo.dia_semana > 7) {
    throw new ApiError(422, "El día de la semana debe ir de 1 a 7");
  }
  if (!HORA.test(nuevo.hora_inicio) || !HORA.test(nuevo.hora_fin)) throw new ApiError(422, "Las horas deben tener el formato HH:MM");
  const ini = minutosHora(nuevo.hora_inicio);
  const fin = minutosHora(nuevo.hora_fin);
  if (fin <= ini) throw new ApiError(422, "La hora de fin debe ser posterior a la de inicio");
  const choca = db.horarios.some(
    (h) =>
      h.profesional_id === prof.id &&
      h.dia_semana === nuevo.dia_semana &&
      seSolapan(ini, fin, minutosHora(h.hora_inicio), minutosHora(h.hora_fin)),
  );
  if (choca) throw new ApiError(409, "Ese bloque se solapa con otro del mismo día");

  const horario: HorarioAtencion = { id: nuevoId(), clinica_id: prof.clinica_id, profesional_id: prof.id, ...nuevo };
  db.horarios.push(horario);
  return red(horario);
}

/**
 * Quita un bloque del horario. El cambio rige hacia adelante: las citas ya reservadas no se
 * cancelan, pero las que quedan fuera de la atención se devuelven para que recepción las reprograme.
 */
export async function eliminarHorario(horarioId: string): Promise<{ conflictos: CitaVista[] }> {
  const { clinica } = sesionConRol(ROLES_QUE_GESTIONAN, "Tu rol no gestiona horarios ni bloqueos");
  const horario = db.horarios.find((h) => h.id === horarioId && h.clinica_id === clinica.id);
  if (!horario) throw new ApiError(404, "Horario no encontrado");
  profesionalAccesible(horario.profesional_id);
  db.horarios.splice(db.horarios.indexOf(horario), 1);
  return red({ conflictos: citasFueraDeHorario(horario.profesional_id) });
}

// ---------- Bloqueos (RF6) ----------

export type BloqueoVista = BloqueoAgenda & { conflictos: CitaVista[] };

/** Bloqueos vigentes o futuros del profesional, con las citas que cada uno deja en conflicto. */
export async function listarBloqueos(profesionalId: string): Promise<BloqueoVista[]> {
  profesionalAccesible(profesionalId);
  return red(
    db.bloqueos
      .filter((b) => b.profesional_id === profesionalId && Date.parse(b.fin) > Date.now())
      .sort((a, b) => Date.parse(a.inicio) - Date.parse(b.inicio))
      .map((b) => ({ ...b, conflictos: conflictosDeBloqueo(b) })),
  );
}

export async function crearBloqueo(profesionalId: string, datos: { inicio: Instante; fin: Instante; motivo: string }): Promise<BloqueoVista> {
  const prof = profesionalAccesible(profesionalId);
  const ini = Date.parse(datos.inicio);
  const fin = Date.parse(datos.fin);
  if (Number.isNaN(ini) || Number.isNaN(fin)) throw new ApiError(422, "Las fechas del bloqueo no son válidas");
  if (fin <= ini) throw new ApiError(422, "El fin del bloqueo debe ser posterior a su inicio");
  if (fin <= Date.now()) throw new ApiError(422, "El bloqueo ya terminó: no tiene efecto sobre la agenda");
  const motivo = datos.motivo.trim();
  if (motivo.length < 3 || motivo.length > 200) throw new ApiError(422, "Indica el motivo (de 3 a 200 caracteres)");

  const bloqueo: BloqueoAgenda = {
    id: nuevoId(),
    clinica_id: prof.clinica_id,
    profesional_id: prof.id,
    inicio: new Date(ini).toISOString(),
    fin: new Date(fin).toISOString(),
    motivo,
  };
  db.bloqueos.push(bloqueo);
  return red({ ...bloqueo, conflictos: conflictosDeBloqueo(bloqueo) });
}

export async function eliminarBloqueo(bloqueoId: string): Promise<void> {
  const { clinica } = sesionConRol(ROLES_QUE_GESTIONAN, "Tu rol no gestiona horarios ni bloqueos");
  const bloqueo = db.bloqueos.find((b) => b.id === bloqueoId && b.clinica_id === clinica.id);
  if (!bloqueo) throw new ApiError(404, "Bloqueo no encontrado");
  profesionalAccesible(bloqueo.profesional_id);
  db.bloqueos.splice(db.bloqueos.indexOf(bloqueo), 1);
  return red(undefined);
}
