import { useSyncExternalStore } from "react";

// Enrutado por hash (#/agenda): sin dependencias y sin configurar el servidor.
const leer = () => window.location.hash.slice(1) || "/";

const suscribir = (aviso: () => void) => {
  window.addEventListener("hashchange", aviso);
  return () => window.removeEventListener("hashchange", aviso);
};

export const useRuta = () => useSyncExternalStore(suscribir, leer);

export const navegar = (path: string) => {
  window.location.hash = path;
};
