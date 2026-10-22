import type { Clinica, Usuario } from "./dominio";
import { crearSemilla, verificarSemilla } from "./semilla";

// Capa de acceso a datos del frontend. Hoy responde desde memoria; cuando exista
// el backend, cada función se cambia por un fetch a la API y las vistas no se tocan.

const db = crearSemilla();
if (import.meta.env.DEV) verificarSemilla(db);

/** Lo que la API sabrá del usuario a partir de su token de Keycloak. */
export type Sesion = Readonly<{ usuario: Usuario; clinica: Clinica | null }>;

// Sesión vigente: las funciones de datos sacarán de aquí la clínica, igual que la API del token.
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
