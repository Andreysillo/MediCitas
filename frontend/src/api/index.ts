import { diaSemanaIso, inicioDelDia, sumarDias } from "../fechas";
import { seSolapan, type BloqueoAgenda, type Cita, type Clinica, type HorarioAtencion, type Usuario } from "./dominio";
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

export const listarProfesionales = () => red(profesionalesDe(sesionDeClinica().clinica.id));

// ---------- Agenda del día (RF20) ----------

export type CitaVista = Cita & { paciente: string; servicio: string };

export type AgendaDia = {
  fecha: string;
  profesionales: ProfesionalVista[];
  horarios: HorarioAtencion[];
  bloqueos: BloqueoAgenda[];
  citas: CitaVista[];
};

/** Agenda de un día: de toda la clínica o de un profesional. */
export function agendaDelDia(fecha: string, profesionalId?: string): Promise<AgendaDia> {
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
    citas: db.citas
      .filter((c) => ids.has(c.profesional_id) && delDia(c))
      .map((c) => ({
        ...c,
        paciente: db.pacientes.find((p) => p.id === c.paciente_id)?.nombre ?? "—",
        servicio: db.servicios.find((s) => s.id === c.servicio_id)?.nombre ?? "—",
      })),
  });
}
