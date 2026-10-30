import { useEffect, useState } from "react";

/**
 * Carga datos de la API cuando cambian las dependencias y expone `recargar` para volver a pedirlos
 * tras una escritura. Si llega una respuesta vieja (cambió algo mientras esperaba), se descarta.
 */
export function useDatos<T>(cargar: () => Promise<T>, deps: readonly unknown[] = []) {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let vigente = true;
    cargar()
      .then((d) => {
        if (!vigente) return;
        setDatos(d);
        setError("");
      })
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
    // `cargar` es una función nueva en cada render; lo que dispara la carga son las dependencias dadas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version]);

  return { datos, error, recargar: () => setVersion((v) => v + 1) };
}

/** Mensaje legible de cualquier error capturado. */
export const mensajeDe = (e: unknown) => (e instanceof Error ? e.message : "Error inesperado");
