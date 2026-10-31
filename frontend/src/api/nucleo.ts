import type { Cita, Clinica, Rol, Usuario } from "./dominio";
import { crearSemilla, verificarSemilla } from "./semilla";

// Núcleo compartido por todos los módulos de la API simulada: la "base" en memoria, los
// errores, la sesión y la bitácora. Lo demás (agenda, pacientes, catálogo...) se apoya en esto.

/** La base de datos en memoria. Solo los módulos de `api/` la tocan; las vistas pasan por las funciones. */
export const db = crearSemilla();
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

// Quien dibuja la app se suscribe para enterarse de entrar, salir o cambiar de usuario.
const oyentesSesion = new Set<() => void>();

export const sesionVigente = () => actual;
export const fijarSesion = (s: Sesion | null) => {
  actual = s;
  oyentesSesion.forEach((o) => o());
};
export const suscribirSesion = (oyente: () => void) => {
  oyentesSesion.add(oyente);
  return () => {
    oyentesSesion.delete(oyente);
  };
};

// Simula la latencia de red y devuelve una copia, para que las vistas manejen la carga
// y no puedan modificar la "base" por accidente.
export const red = <T,>(valor: T) =>
  new Promise<T>((ok) => setTimeout(() => ok(structuredClone(valor)), 150 + Math.random() * 150));

/**
 * Sesión con clínica. Toda consulta filtra por esta clínica y por ninguna otra (I5).
 * También comprueba `activo` en cada solicitud: una baja lógica corta el acceso de inmediato,
 * sin esperar a que el token expire (decisión abierta 2 del documento de diseño).
 */
export function sesionDeClinica() {
  if (!actual) throw new ApiError(401, "No hay sesión iniciada");
  const { usuario, clinica } = actual;
  if (!usuario.activo) throw new ApiError(403, "Tu usuario fue dado de baja");
  if (!clinica) throw new ApiError(403, "Este usuario no pertenece a ninguna clínica");
  return { usuario, clinica };
}

/** Sesión con alguno de los roles dados; si no, 403. */
export function sesionConRol(roles: readonly Rol[], mensaje: string) {
  const sesion = sesionDeClinica();
  if (!roles.includes(sesion.usuario.rol)) throw new ApiError(403, mensaje);
  return sesion;
}

/** Sesión del administrador de plataforma, que no pertenece a ninguna clínica y no ve datos clínicos. */
export function sesionPlataforma() {
  if (!actual) throw new ApiError(401, "No hay sesión iniciada");
  if (actual.usuario.rol !== "ADM_PLATAFORMA" || !actual.usuario.activo) {
    throw new ApiError(403, "Solo el administrador de plataforma da de alta clínicas");
  }
  return actual.usuario;
}

/** `tiene_nota` solo es cierto para un profesional: para los demás roles ni siquiera se revela si existe una nota. */
export type CitaVista = Cita & { paciente: string; servicio: string; tiene_nota: boolean };

export const citaVista = (c: Cita): CitaVista => ({
  ...c,
  paciente: db.pacientes.find((p) => p.id === c.paciente_id)?.nombre ?? "—",
  servicio: db.servicios.find((s) => s.id === c.servicio_id)?.nombre ?? "—",
  tiene_nota: actual?.usuario.rol === "PROFESIONAL" && db.notas.some((n) => n.cita_id === c.id),
});

/** Minúsculas y sin tildes, para buscar "maria" y encontrar "María". */
export const sinTildes = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export const nombreUsuario = (id: string) => db.usuarios.find((u) => u.id === id)?.nombre ?? "—";

// randomUUID solo existe en contextos seguros (https o localhost); si se abre por IP, se usa el respaldo.
export const nuevoId = () => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/** Bitácora append-only (RF18). La API no ofrece ninguna función para modificarla ni borrarla (I6). */
export function auditar(
  usuarioId: string,
  clinicaId: string,
  pacienteId: string,
  accion: "LECTURA" | "ESCRITURA",
  recurso: "NOTA_CLINICA" | "CONTACTO_PACIENTE" = "CONTACTO_PACIENTE",
) {
  db.auditoria.push({
    id: db.auditoria.length + 1,
    clinica_id: clinicaId,
    usuario_id: usuarioId,
    paciente_id: pacienteId,
    accion,
    recurso,
    ocurrido_en: new Date().toISOString(),
  });
}
