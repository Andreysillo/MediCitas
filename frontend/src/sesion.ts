import { useSyncExternalStore } from "react";
import { cerrarSesion, iniciarSesion, sesionVigente, suscribirSesion } from "./api";

// Sesión de la demo. Es el único punto que cambia al conectar Keycloak:
// - entrarComo(id) pasará a ser la redirección al login de Keycloak (la pantalla /entrar desaparece);
// - la sesión (usuario, clínica, rol) se leerá del token en vez de la lista de usuarios de prueba;
// - salir() llamará al logout de Keycloak.
// Las vistas solo usan useSesion(), así que no cambian.

const CLAVE = "medicitas.demo.usuario";

// Recarga de página: se recupera el usuario elegido. Los ids de la semilla son fijos, así que siguen
// valiendo; si ya no existe (por ejemplo, un usuario creado antes de recargar), se vuelve a /entrar.
try {
  const id = sessionStorage.getItem(CLAVE);
  if (id) iniciarSesion(id);
} catch {
  // Sin almacenamiento o con un id que ya no existe: se entra de nuevo.
}

export const useSesion = () => useSyncExternalStore(suscribirSesion, sesionVigente);

export function entrarComo(usuarioId: string) {
  const sesion = iniciarSesion(usuarioId);
  try {
    sessionStorage.setItem(CLAVE, usuarioId);
  } catch {
    // Sin almacenamiento la sesión dura hasta recargar.
  }
  return sesion;
}

export function salir() {
  cerrarSesion();
  try {
    sessionStorage.removeItem(CLAVE);
  } catch {
    // Nada guardado.
  }
}
