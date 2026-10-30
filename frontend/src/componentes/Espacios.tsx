import { useEffect, useState } from "react";
import { disponibilidad, type DisponibilidadProfesional, type ProfesionalVista } from "../api";
import { fechaCorta, hora, hoy, sumarDias } from "../fechas";
import "./espacios.css";

const DIAS = 7;
const VISIBLES_POR_DIA = 6;

export type Espacio = { profesional: ProfesionalVista; inicio: string };

type Props = Readonly<{
  servicioId: string;
  /** Cita que se está reprogramando: su espacio actual se muestra libre. */
  ignorarCitaId?: string;
  elegido: Espacio | null;
  onElegir: (e: Espacio) => void;
  /** Al cambiar, vuelve a consultar (por ejemplo tras un intento de reserva fallido). */
  version: number;
}>;

/** Espacios libres de una semana para un servicio, agrupados por profesional (RF7, RF8). */
export default function Espacios({ servicioId, ignorarCitaId, elegido, onElegir, version }: Props) {
  const [desde, setDesde] = useState(hoy);
  const [dispo, setDispo] = useState<DisponibilidadProfesional[] | null>(null);
  const [cargando, setCargando] = useState(false);

  // Se consulta de nuevo al cambiar de servicio, de semana o de version: así el espacio
  // recién tomado desaparece de inmediato (I7, I8).
  useEffect(() => {
    let vigente = true;
    setCargando(true);
    disponibilidad(servicioId, desde, DIAS, ignorarCitaId)
      .then((d) => vigente && setDispo(d))
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, [servicioId, ignorarCitaId, desde, version]);

  return (
    <div className="espacios" aria-busy={cargando}>
      <div className="semana-nav">
        <button type="button" className="btn btn-icon" aria-label="Semana anterior" disabled={desde <= hoy()} onClick={() => setDesde(sumarDias(desde, -DIAS))}>
          ‹
        </button>
        <span>
          {fechaCorta(desde)} — {fechaCorta(sumarDias(desde, DIAS - 1))}
        </span>
        <button type="button" className="btn btn-icon" aria-label="Semana siguiente" onClick={() => setDesde(sumarDias(desde, DIAS))}>
          ›
        </button>
      </div>
      {dispo?.map((d) => (
        <TarjetaProfesional key={d.profesional.id} dispo={d} elegido={elegido} onElegir={onElegir} />
      ))}
      {dispo?.length === 0 && <p className="aviso">Ningún profesional atiende este servicio.</p>}
    </div>
  );
}

type TarjetaProps = Readonly<{ dispo: DisponibilidadProfesional; elegido: Espacio | null; onElegir: (e: Espacio) => void }>;

function TarjetaProfesional({ dispo, elegido, onElegir }: TarjetaProps) {
  const [abiertos, setAbiertos] = useState<string[]>([]);
  const { profesional, dias } = dispo;
  const total = dias.reduce((n, d) => n + d.espacios.length, 0);

  return (
    <article className="prof-card">
      <header>
        <strong>{profesional.nombre}</strong>
        <span>
          {profesional.especialidad} · {total === 0 ? "sin espacios esta semana" : `${total} espacios esta semana`}
        </span>
      </header>
      <div className="semana">
        {dias.map((d) => {
          const abierto = abiertos.includes(d.fecha);
          const visibles = abierto ? d.espacios : d.espacios.slice(0, VISIBLES_POR_DIA);
          const ocultos = d.espacios.length - visibles.length;
          return (
            <div key={d.fecha} className="dia">
              <h3>{fechaCorta(d.fecha)}</h3>
              {d.espacios.length === 0 && <span className="dia-vacio">—</span>}
              {visibles.map((inicio) => (
                <button
                  key={inicio}
                  type="button"
                  className="slot"
                  aria-pressed={elegido?.inicio === inicio && elegido.profesional.id === profesional.id}
                  aria-label={`${fechaCorta(d.fecha)}, ${hora(inicio)}, con ${profesional.nombre}`}
                  onClick={() => onElegir({ profesional, inicio })}
                >
                  {hora(inicio)}
                </button>
              ))}
              {ocultos > 0 && (
                <button type="button" className="slot slot-mas" onClick={() => setAbiertos([...abiertos, d.fecha])}>
                  +{ocultos}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </article>
  );
}
