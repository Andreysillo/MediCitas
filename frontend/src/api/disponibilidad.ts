import { inicioDelDia, minutosHora } from "../fechas";
import { seSolapan, type HorarioAtencion } from "./dominio";

// Cálculo de espacios disponibles (RF7). Es una función pura a propósito: es el mismo
// algoritmo que implementará el backend, y así se puede razonar y probar por separado.

/** Cada cuánto puede empezar una cita dentro de un bloque del horario. */
export const PASO_MINUTOS = 15;

const MIN = 60_000;

/** Instante (ms) de una hora "08:30" en una fecha local "YYYY-MM-DD". */
export const instanteEn = (fecha: string, hora: string) => {
  const d = inicioDelDia(fecha);
  d.setMinutes(minutosHora(hora));
  return d.getTime();
};

type Intervalo = readonly [number, number];

/**
 * Inicios posibles para una cita de `duracion` minutos en `fecha`:
 * - dentro de algún bloque del horario de ese día (I3),
 * - sin tocar ningún intervalo ocupado: citas vigentes y bloqueos (I1, RF6),
 * - y solo en el futuro.
 */
export function espaciosLibres(
  fecha: string,
  duracion: number,
  horariosDelDia: readonly HorarioAtencion[],
  ocupados: readonly Intervalo[],
  ahora: number,
): number[] {
  const libres: number[] = [];
  for (const h of horariosDelDia) {
    const finBloque = instanteEn(fecha, h.hora_fin);
    for (let t = instanteEn(fecha, h.hora_inicio); t + duracion * MIN <= finBloque; t += PASO_MINUTOS * MIN) {
      const fin = t + duracion * MIN;
      if (t > ahora && !ocupados.some(([a, b]) => seSolapan(t, fin, a, b))) libres.push(t);
    }
  }
  return libres.sort((a, b) => a - b);
}
