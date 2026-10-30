import { diaSemanaIso, fechaLocal, inicioDelDia, sumarDias } from "../fechas";
import { espaciosLibres, instanteEn } from "./disponibilidad";
import {
  ESTADO_NOMBRE,
  ROLES_QUE_AGENDAN,
  ROLES_QUE_REGISTRAN_DESENLACE,
  esVigente,
  puedeTransicionar,
  seSolapan,
  type BloqueoAgenda,
  type Cita,
  type Clinica,
  type EstadoCita,
  type HorarioAtencion,
  type Instante,
  type Paciente,
  type Usuario,
} from "./dominio";
import { crearSemilla, verificarSemilla } from "./semilla";

// Capa de acceso a datos del frontend. Hoy responde desde memoria; cuando exista
// el backend, cada función se cambia por un fetch a la API y las vistas no se tocan.

const db = crearSemilla();
if (import.meta.env.DEV) verificarSemilla(db);

/** Error con el mismo código HTTP que devolverá la API real (401, 403, 404, 409, 422). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    mensaje: string,
  ) {
    super(mensaje);
  }
}

/** Lo que la API sabrá del usuario a partir de su token de Keycloak. */
export type Sesion = Readonly<{ usuario: Usuario; clinica: Clinica | null }>;

// Sesión vigente: las funciones de datos sacan de aquí la clínica, igual que la API del token.
let actual: Sesion | null = null;

/** Usuarios de prueba agrupados por clínica, para el selector "Ver como". */
export function usuariosDePrueba() {
  const grupos = [{ etiqueta: "Plataforma", usuarios: db.usuarios.filter((u) => u.clinica_id === null) }];
  for (const c of db.clinicas) {
    grupos.push({ etiqueta: c.nombre, usuarios: db.usuarios.filter((u) => u.clinica_id === c.id) });
  }
  return grupos;
}

/**
 * Simula el inicio de sesión. Con Keycloak la clínica y el rol vendrán dentro del token,
 * y la API tomará la clínica de ahí, nunca de un parámetro de la solicitud (I5).
 */
export function iniciarSesion(usuarioId: string): Sesion {
  const usuario = db.usuarios.find((u) => u.id === usuarioId);
  if (!usuario) throw new Error(`Usuario de prueba inexistente: ${usuarioId}`);
  actual = { usuario, clinica: db.clinicas.find((c) => c.id === usuario.clinica_id) ?? null };
  return actual;
}

// ---------- Utilidades internas ----------

// Simula la latencia de red y devuelve una copia, para que las vistas manejen la carga
// y no puedan modificar la "base" por accidente.
const red = <T,>(valor: T) =>
  new Promise<T>((ok) => setTimeout(() => ok(structuredClone(valor)), 150 + Math.random() * 150));

/** Sesión con clínica. Toda consulta filtra por esta clínica y por ninguna otra (I5). */
function sesionDeClinica() {
  if (!actual) throw new ApiError(401, "No hay sesión iniciada");
  const { usuario, clinica } = actual;
  if (!clinica) throw new ApiError(403, "Este usuario no pertenece a ninguna clínica");
  return { usuario, clinica };
}

const nombreUsuario = (id: string) => db.usuarios.find((u) => u.id === id)?.nombre ?? "—";

// ---------- Profesionales ----------

export type ProfesionalVista = { id: string; nombre: string; especialidad: string };

const profesionalesDe = (clinicaId: string): ProfesionalVista[] =>
  db.profesionales
    .filter((p) => p.clinica_id === clinicaId && p.activo)
    .map((p) => ({
      id: p.id,
      nombre: nombreUsuario(p.usuario_id),
      especialidad: db.especialidades.find((e) => e.id === p.especialidad_id)?.nombre ?? "—",
    }));

// async: así un error de sesión llega como promesa rechazada al .catch de la vista.
export const listarProfesionales = async () => red(profesionalesDe(sesionDeClinica().clinica.id));

// ---------- Agenda del día (RF20) ----------

export type CitaVista = Cita & { paciente: string; servicio: string };

const citaVista = (c: Cita): CitaVista => ({
  ...c,
  paciente: db.pacientes.find((p) => p.id === c.paciente_id)?.nombre ?? "—",
  servicio: db.servicios.find((s) => s.id === c.servicio_id)?.nombre ?? "—",
});

export type AgendaDia = {
  fecha: string;
  profesionales: ProfesionalVista[];
  horarios: HorarioAtencion[];
  bloqueos: BloqueoAgenda[];
  citas: CitaVista[];
};

/** Agenda de un día: de toda la clínica o de un profesional. */
export async function agendaDelDia(fecha: string, profesionalId?: string): Promise<AgendaDia> {
  const { usuario, clinica } = sesionDeClinica();
  // Parte de los profesionales de la clínica de la sesión: un id de otra clínica no encuentra nada.
  let profesionales = profesionalesDe(clinica.id);

  if (usuario.rol === "PROFESIONAL") {
    // Un profesional solo ve su propia agenda, aunque pida la de otro.
    const propio = db.profesionales.find((p) => p.usuario_id === usuario.id);
    profesionales = profesionales.filter((p) => p.id === propio?.id);
  } else if (profesionalId) {
    profesionales = profesionales.filter((p) => p.id === profesionalId);
  }

  const ids = new Set(profesionales.map((p) => p.id));
  const ini = inicioDelDia(fecha).getTime();
  const fin = inicioDelDia(sumarDias(fecha, 1)).getTime();
  const delDia = (x: { inicio: string; fin: string }) => seSolapan(ini, fin, Date.parse(x.inicio), Date.parse(x.fin));
  const dia = diaSemanaIso(fecha);

  return red({
    fecha,
    profesionales,
    horarios: db.horarios.filter((h) => ids.has(h.profesional_id) && h.dia_semana === dia),
    bloqueos: db.bloqueos.filter((b) => ids.has(b.profesional_id) && delDia(b)),
    citas: db.citas.filter((c) => ids.has(c.profesional_id) && delDia(c)).map(citaVista),
  });
}

// ---------- Servicios ----------

export type ServicioVista = { id: string; nombre: string; duracion_minutos: number; especialidad: string };

export async function listarServicios(): Promise<ServicioVista[]> {
  const { clinica } = sesionDeClinica();
  return red(
    db.servicios
      .filter((s) => s.clinica_id === clinica.id && s.activo)
      .map((s) => ({
        id: s.id,
        nombre: s.nombre,
        duracion_minutos: s.duracion_minutos,
        especialidad: db.especialidades.find((e) => e.id === s.especialidad_id)?.nombre ?? "—",
      })),
  );
}

// ---------- Disponibilidad (RF7, RF8) ----------

export type DisponibilidadProfesional = {
  profesional: ProfesionalVista;
  dias: { fecha: string; espacios: Instante[] }[];
};

const MIN = 60_000;

/**
 * Intervalos ocupados de un profesional: sus citas vigentes y sus bloqueos.
 * `ignorar` es la cita que se está reprogramando: su espacio se libera dentro de la misma
 * transacción (RF10), así que no debe contar como ocupado para elegir el nuevo.
 */
const ocupadosDe = (profesionalId: string, ignorar?: string) => [
  ...db.citas
    .filter((c) => c.profesional_id === profesionalId && c.id !== ignorar && esVigente(c.estado))
    .map((c) => [Date.parse(c.inicio), Date.parse(c.fin)] as const),
  ...db.bloqueos
    .filter((b) => b.profesional_id === profesionalId)
    .map((b) => [Date.parse(b.inicio), Date.parse(b.fin)] as const),
];

const horariosDe = (profesionalId: string, fecha: string) =>
  db.horarios.filter((h) => h.profesional_id === profesionalId && h.dia_semana === diaSemanaIso(fecha));

/** Disponibilidad de un servicio en un rango de días: qué profesionales tienen espacio y cuáles son. */
export async function disponibilidad(
  servicioId: string,
  desde: string,
  dias: number,
  ignorarCitaId?: string,
): Promise<DisponibilidadProfesional[]> {
  const { clinica } = sesionDeClinica();
  const servicio = db.servicios.find((s) => s.id === servicioId && s.clinica_id === clinica.id);
  if (!servicio) throw new ApiError(404, "Servicio no encontrado");
  if (dias < 1 || dias > 31) throw new ApiError(422, "El rango debe ser de 1 a 31 días");

  // Solo los profesionales habilitados para ese servicio (profesional_servicio).
  const habilitados = new Set(db.profesionalServicio.filter((ps) => ps.servicio_id === servicio.id).map((ps) => ps.profesional_id));
  const fechas = Array.from({ length: dias }, (_, i) => sumarDias(desde, i));
  const ahora = Date.now();

  return red(
    profesionalesDe(clinica.id)
      .filter((p) => habilitados.has(p.id))
      .map((profesional) => {
        const ocupados = ocupadosDe(profesional.id, ignorarCitaId);
        return {
          profesional,
          dias: fechas.map((fecha) => ({
            fecha,
            espacios: espaciosLibres(fecha, servicio.duracion_minutos, horariosDe(profesional.id, fecha), ocupados, ahora).map(
              (ms) => new Date(ms).toISOString(),
            ),
          })),
        };
      }),
  );
}

// ---------- Pacientes ----------

export type PacienteResumen = Pick<Paciente, "id" | "nombre" | "identificacion">;

const sinTildes = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/**
 * Busca por nombre o identificación. No devuelve teléfono ni correo a propósito:
 * leer datos de contacto se audita (RF18) y para elegir un paciente no hacen falta.
 */
export async function buscarPacientes(texto: string): Promise<PacienteResumen[]> {
  const { clinica } = sesionDeClinica();
  const q = sinTildes(texto.trim());
  if (q.length < 2) return [];
  return red(
    db.pacientes
      .filter((p) => p.clinica_id === clinica.id && (sinTildes(p.nombre).includes(q) || p.identificacion.includes(q)))
      .slice(0, 8)
      .map(({ id, nombre, identificacion }) => ({ id, nombre, identificacion })),
  );
}

// ---------- Reserva (RF9) ----------

/** Lo que envía el cliente. No lleva `fin` ni `clinica_id`: el fin lo fija el servicio (I4) y la clínica la sesión (I5). */
export type SolicitudReserva = { paciente_id: string; profesional_id: string; servicio_id: string; inicio: Instante };

// randomUUID solo existe en contextos seguros (https o localhost); si se abre por IP, se usa el respaldo.
const nuevoId = () => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function insertarCita(sol: SolicitudReserva, fin: number, creada_por: string, clinica_id: string, origen: string | null = null): Cita {
  const cita: Cita = {
    id: nuevoId(),
    clinica_id,
    ...sol,
    inicio: new Date(Date.parse(sol.inicio)).toISOString(),
    fin: new Date(fin).toISOString(),
    estado: "RESERVADA",
    creada_por,
    creada_en: new Date().toISOString(),
    cancelada_por: null,
    cancelada_en: null,
    motivo_cancelacion: null,
    cita_origen_id: origen,
  };
  db.citas.push(cita);
  return cita;
}

/**
 * Reglas que debe cumplir un espacio para recibir una cita. Las comparten reservar y
 * reprogramar, para que ambas operaciones nunca discrepen. `ignorar` es la cita que se
 * está moviendo: en la base su estado pasa a REPROGRAMADA antes del insert, así que
 * ya no cuenta para I1 ni I2.
 */
function validarEspacio(clinicaId: string, sol: SolicitudReserva, ignorar?: string) {
  // Un id de otra clínica se trata igual que uno inexistente: no se revela que existe (I5).
  const paciente = db.pacientes.find((p) => p.id === sol.paciente_id && p.clinica_id === clinicaId);
  const profesional = db.profesionales.find((p) => p.id === sol.profesional_id && p.clinica_id === clinicaId);
  const servicio = db.servicios.find((s) => s.id === sol.servicio_id && s.clinica_id === clinicaId);
  if (!paciente || !profesional || !servicio) {
    throw new ApiError(422, "El paciente, el profesional o el servicio no existen en esta clínica");
  }
  if (!db.profesionalServicio.some((ps) => ps.profesional_id === profesional.id && ps.servicio_id === servicio.id)) {
    throw new ApiError(422, "El profesional no atiende ese servicio");
  }

  const ini = Date.parse(sol.inicio);
  if (Number.isNaN(ini)) throw new ApiError(422, "La hora de inicio no es válida");
  if (ini <= Date.now()) throw new ApiError(422, "No se puede reservar en el pasado");
  const fin = ini + servicio.duracion_minutos * MIN; // I4: la duración la decide el servicio

  // I3: dentro del horario de atención y fuera de los bloqueos.
  const fecha = fechaLocal(new Date(ini));
  const enHorario = horariosDe(profesional.id, fecha).some(
    (h) => ini >= instanteEn(fecha, h.hora_inicio) && fin <= instanteEn(fecha, h.hora_fin),
  );
  if (!enHorario) throw new ApiError(422, "Ese horario está fuera de la atención del profesional");
  const bloqueado = db.bloqueos.some(
    (b) => b.profesional_id === profesional.id && seSolapan(ini, fin, Date.parse(b.inicio), Date.parse(b.fin)),
  );
  if (bloqueado) throw new ApiError(422, "El profesional tiene un bloqueo de agenda en ese horario");

  // I1 e I2: ningún solape con citas vigentes del profesional ni del paciente.
  const choques = db.citas.filter(
    (c) => c.id !== ignorar && esVigente(c.estado) && seSolapan(ini, fin, Date.parse(c.inicio), Date.parse(c.fin)),
  );
  if (choques.some((c) => c.profesional_id === profesional.id)) throw new ApiError(409, "Ese espacio ya fue tomado");
  if (choques.some((c) => c.paciente_id === paciente.id)) throw new ApiError(409, "El paciente ya tiene otra cita a esa hora");

  return fin;
}

/**
 * Reserva una cita. Mismos desenlaces que la API real:
 * concedida (201), espacio ya tomado (409) o solicitud inválida (422).
 *
 * ponytail: aquí JavaScript ejecuta todo de corrido y no hay carrera real. En el backend,
 * quien decide entre dos reservas simultáneas es la restricción de exclusión de PostgreSQL.
 */
export async function reservarCita(sol: SolicitudReserva): Promise<CitaVista> {
  const { usuario, clinica } = sesionDeClinica();
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede reservar citas");
  const fin = validarEspacio(clinica.id, sol);
  return red(citaVista(insertarCita(sol, fin, usuario.id, clinica.id)));
}

/**
 * Solo para la demostración: otra recepcionista reserva ese mismo espacio para otro
 * paciente justo antes. Permite ver en la interfaz el desenlace 409 de la pregunta rectora.
 */
export function simularReservaAjena(sol: SolicitudReserva) {
  const { clinica } = sesionDeClinica();
  const servicio = db.servicios.find((s) => s.id === sol.servicio_id && s.clinica_id === clinica.id);
  const recepcion = db.usuarios.find((u) => u.clinica_id === clinica.id && u.rol === "RECEPCION");
  if (!servicio || !recepcion) return;
  const ini = Date.parse(sol.inicio);
  const fin = ini + servicio.duracion_minutos * MIN;
  const libre = (p: Paciente) =>
    !db.citas.some((c) => c.paciente_id === p.id && esVigente(c.estado) && seSolapan(ini, fin, Date.parse(c.inicio), Date.parse(c.fin)));
  const otro = db.pacientes.find((p) => p.clinica_id === clinica.id && p.id !== sol.paciente_id && libre(p));
  if (otro) insertarCita({ ...sol, paciente_id: otro.id }, fin, recepcion.id, clinica.id);
}

// ---------- Ciclo de vida de la cita (RF10 a RF13) ----------

/** Busca una cita de la clínica de la sesión. Un profesional solo alcanza las suyas. */
function buscarCita(citaId: string) {
  const { usuario, clinica } = sesionDeClinica();
  const cita = db.citas.find((c) => c.id === citaId && c.clinica_id === clinica.id);
  const propio = db.profesionales.find((p) => p.usuario_id === usuario.id);
  // Misma respuesta para "no existe" y "es de otra clínica o de otro profesional" (I5).
  if (!cita || (usuario.rol === "PROFESIONAL" && cita.profesional_id !== propio?.id)) {
    throw new ApiError(404, "Cita no encontrada");
  }
  return { cita, usuario, clinica };
}

/**
 * RF13: único punto por donde cambia el estado de una cita. Si la transición no está en
 * la tabla, se rechaza con 409. En la base lo reforzará un trigger.
 */
function exigirTransicion(cita: Cita, a: EstadoCita) {
  if (!puedeTransicionar(cita.estado, a)) {
    throw new ApiError(409, `Una cita ${ESTADO_NOMBRE[cita.estado].toLowerCase()} no puede pasar a ${ESTADO_NOMBRE[a].toLowerCase()}`);
  }
}

function transicionar(cita: Cita, a: EstadoCita) {
  exigirTransicion(cita, a);
  cita.estado = a;
}

/** RF12: registra si el paciente fue atendido o no se presentó. Solo después de la hora de inicio. */
export async function registrarDesenlace(citaId: string, desenlace: "ATENDIDA" | "AUSENTE"): Promise<CitaVista> {
  const { cita, usuario } = buscarCita(citaId);
  if (!ROLES_QUE_REGISTRAN_DESENLACE.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede registrar el desenlace");
  if (desenlace !== "ATENDIDA" && desenlace !== "AUSENTE") throw new ApiError(422, "El desenlace debe ser atendida o ausente");
  exigirTransicion(cita, desenlace);
  if (Date.parse(cita.inicio) > Date.now()) {
    throw new ApiError(422, "El desenlace solo se registra una vez pasada la hora de inicio");
  }
  transicionar(cita, desenlace);
  return red(citaVista(cita));
}

/** RF11: cancela dejando el motivo y quién lo hizo. Libera el espacio de inmediato (I7). */
export async function cancelarCita(citaId: string, motivo: string): Promise<CitaVista> {
  const { cita, usuario } = buscarCita(citaId);
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede cancelar citas");
  if (motivo.trim().length < 3) throw new ApiError(422, "Indica el motivo de la cancelación");
  transicionar(cita, "CANCELADA");
  cita.cancelada_por = usuario.id;
  cita.cancelada_en = new Date().toISOString();
  cita.motivo_cancelacion = motivo.trim();
  return red(citaVista(cita));
}

/**
 * RF10: mueve una cita a otro espacio. No edita la cita: la antigua pasa a REPROGRAMADA y
 * se crea una nueva que apunta a ella (cita_origen_id). El servicio no cambia, así que la
 * duración tampoco (I4).
 *
 * Todo se valida antes de tocar nada, así que o se hacen los dos cambios o ninguno: si el
 * nuevo espacio está tomado, la cita original sigue reservada. En la base esto es una sola
 * transacción: UPDATE de la antigua e INSERT de la nueva se confirman juntos.
 */
export async function reprogramarCita(citaId: string, destino: { profesional_id: string; inicio: Instante }): Promise<CitaVista> {
  const { cita, usuario, clinica } = buscarCita(citaId);
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede reprogramar citas");
  exigirTransicion(cita, "REPROGRAMADA");

  const sol: SolicitudReserva = { paciente_id: cita.paciente_id, servicio_id: cita.servicio_id, ...destino };
  if (destino.profesional_id === cita.profesional_id && Date.parse(destino.inicio) === Date.parse(cita.inicio)) {
    throw new ApiError(422, "Elige un espacio distinto al actual");
  }
  const fin = validarEspacio(clinica.id, sol, cita.id);

  transicionar(cita, "REPROGRAMADA");
  return red(citaVista(insertarCita(sol, fin, usuario.id, clinica.id, cita.id)));
}
