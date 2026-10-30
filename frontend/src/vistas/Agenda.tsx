import { useEffect, useState, type CSSProperties } from "react";
import { agendaDelDia, listarProfesionales, type AgendaDia, type CitaVista, type ProfesionalVista, type Sesion } from "../api";
import { ESTADO_NOMBRE, esVigente, seSolapan, type EstadoCita } from "../api/dominio";
import { fechaLarga, hoy, hora, inicioDelDia, minutosHora, sumarDias } from "../fechas";
import DetalleCita from "./DetalleCita";
import "./agenda.css";

const ESTADOS = Object.keys(ESTADO_NOMBRE) as EstadoCita[];

// Posición vertical de un bloque: minutos desde el inicio del eje y duración en minutos.
// El CSS los convierte a píxeles con --px-min.
const posicion = (ini: number, dur: number) => ({ "--ini": ini, "--dur": dur }) as CSSProperties;

type Props = Readonly<{ sesion: Sesion }>;

export default function Agenda({ sesion }: Props) {
  const esProfesional = sesion.usuario.rol === "PROFESIONAL";
  const [fecha, setFecha] = useState(hoy);
  const [filtro, setFiltro] = useState("");
  const [profesionales, setProfesionales] = useState<ProfesionalVista[]>([]);
  const [agenda, setAgenda] = useState<AgendaDia | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  // Cita abierta en el diálogo de detalle, y mensaje de la última acción realizada.
  const [abierta, setAbierta] = useState<{ cita: CitaVista; conflicto: boolean } | null>(null);
  const [aviso, setAviso] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!esProfesional) listarProfesionales().then(setProfesionales);
  }, [esProfesional]);

  useEffect(() => setAviso(""), [fecha, filtro]);

  // "vigente" descarta respuestas viejas si el usuario cambia de día antes de que lleguen.
  useEffect(() => {
    let vigente = true;
    setCargando(true);
    agendaDelDia(fecha, filtro || undefined)
      .then((a) => {
        if (!vigente) return;
        setAgenda(a);
        setError("");
      })
      .catch((e: Error) => vigente && setError(e.message))
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, [fecha, filtro, version]);

  return (
    <div className="agenda" aria-busy={cargando}>
      <div className="agenda-toolbar">
        <div className="day-nav" role="group" aria-label="Cambiar de día">
          <button type="button" className="btn btn-icon" aria-label="Día anterior" onClick={() => setFecha(sumarDias(fecha, -1))}>
            ‹
          </button>
          <button type="button" className="btn" disabled={fecha === hoy()} onClick={() => setFecha(hoy())}>
            Hoy
          </button>
          <button type="button" className="btn btn-icon" aria-label="Día siguiente" onClick={() => setFecha(sumarDias(fecha, 1))}>
            ›
          </button>
        </div>

        <label className="field">
          <span>Fecha</span>
          <input type="date" value={fecha} onChange={(e) => e.target.value && setFecha(e.target.value)} />
        </label>

        {!esProfesional && (
          <label className="field">
            <span>Profesional</span>
            <select value={filtro} onChange={(e) => setFiltro(e.target.value)}>
              <option value="">Toda la clínica</option>
              {profesionales.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </label>
        )}

        {!esProfesional && (
          <a className="btn btn-cta" href="#/reservar">
            Reservar cita
          </a>
        )}
      </div>

      <div className="agenda-titulo">
        <h2>{fechaLarga(fecha)}</h2>
        {agenda && <Resumen citas={agenda.citas} />}
      </div>

      {aviso && (
        <p className="aviso aviso-ok" role="status">
          {aviso}
        </p>
      )}
      {error && (
        <p className="aviso aviso-error" role="alert">
          {error}
        </p>
      )}
      {!agenda && !error && <p className="aviso">Cargando agenda…</p>}
      {agenda && <Calendario agenda={agenda} esHoy={fecha === hoy()} onAbrir={(cita, conflicto) => setAbierta({ cita, conflicto })} />}

      {abierta && (
        <DetalleCita
          key={abierta.cita.id}
          cita={abierta.cita}
          conflicto={abierta.conflicto}
          profesional={agenda?.profesionales.find((p) => p.id === abierta.cita.profesional_id)?.nombre ?? "—"}
          rol={sesion.usuario.rol}
          onCerrar={() => setAbierta(null)}
          onCambio={(mensaje) => {
            setAviso(mensaje);
            setVersion((v) => v + 1);
          }}
        />
      )}
    </div>
  );
}

function Resumen({ citas }: Readonly<{ citas: CitaVista[] }>) {
  if (citas.length === 0) return <p className="resumen-vacio">Sin citas este día</p>;
  const conteo = (estado: EstadoCita) => citas.filter((c) => c.estado === estado).length;
  return (
    <ul className="resumen" aria-label="Citas del día por estado">
      {ESTADOS.filter((e) => conteo(e) > 0).map((e) => (
        <li key={e} data-estado={e}>
          <strong>{conteo(e)}</strong> {ESTADO_NOMBRE[e].toLowerCase()}
          {conteo(e) > 1 && "s"}
        </li>
      ))}
    </ul>
  );
}

type CalendarioProps = Readonly<{ agenda: AgendaDia; esHoy: boolean; onAbrir: (cita: CitaVista, conflicto: boolean) => void }>;

function Calendario({ agenda, esHoy, onAbrir }: CalendarioProps) {
  const { profesionales, horarios, bloqueos, citas, fecha } = agenda;
  if (profesionales.length === 0) return <p className="aviso">No hay profesionales para mostrar.</p>;
  if (horarios.length === 0) return <p className="aviso">Ningún profesional atiende este día.</p>;

  // El eje va de la primera hora de apertura a la última de cierre, redondeado a horas completas.
  const desde = Math.floor(Math.min(...horarios.map((h) => minutosHora(h.hora_inicio))) / 60) * 60;
  const hasta = Math.ceil(Math.max(...horarios.map((h) => minutosHora(h.hora_fin))) / 60) * 60;
  const horas = Array.from({ length: (hasta - desde) / 60 }, (_, i) => desde + i * 60);

  // Minutos de un instante relativos al eje, recortados a la parte visible
  // (un bloqueo de varios días empieza antes o termina después de este día).
  const medianoche = inicioDelDia(fecha).getTime();
  const enEje = (instante: string) =>
    Math.min(hasta, Math.max(desde, (Date.parse(instante) - medianoche) / 60_000)) - desde;
  const ahora = (Date.now() - medianoche) / 60_000;

  // Solo las citas vigentes ocupan espacio; las canceladas y reprogramadas cuentan en el resumen.
  const vigentes = citas.filter((c) => esVigente(c.estado));

  return (
    <div className="calendario" style={{ "--cols": profesionales.length, "--min-total": hasta - desde } as CSSProperties}>
      <div className="cal-eje" aria-hidden="true">
        {horas.map((m) => (
          <span key={m} style={posicion(m - desde, 60)}>
            {String(m / 60).padStart(2, "0")}:00
          </span>
        ))}
      </div>

      {profesionales.map((p) => {
        const susBloqueos = bloqueos.filter((b) => b.profesional_id === p.id);
        const susCitas = vigentes.filter((c) => c.profesional_id === p.id);
        return (
          <section key={p.id} className="cal-col" aria-label={`Agenda de ${p.nombre}`}>
            <header className="cal-head">
              <strong>{p.nombre}</strong>
              <span>
                {p.especialidad} · {susCitas.length} {susCitas.length === 1 ? "cita" : "citas"}
              </span>
            </header>

            <div className="cal-cuerpo">
              {horarios
                .filter((h) => h.profesional_id === p.id)
                .map((h) => (
                  <div
                    key={h.id}
                    className="cal-abierto"
                    style={posicion(minutosHora(h.hora_inicio) - desde, minutosHora(h.hora_fin) - minutosHora(h.hora_inicio))}
                  />
                ))}

              {susBloqueos.map((b) => (
                <div key={b.id} className="cal-bloqueo" style={posicion(enEje(b.inicio), enEje(b.fin) - enEje(b.inicio))}>
                  Bloqueo: {b.motivo}
                </div>
              ))}

              {susCitas.map((c) => {
                // RF6: una cita reservada dentro de un bloqueo es un conflicto que recepción debe reprogramar.
                const conflicto =
                  c.estado === "RESERVADA" &&
                  susBloqueos.some((b) => seSolapan(Date.parse(c.inicio), Date.parse(c.fin), Date.parse(b.inicio), Date.parse(b.fin)));
                return <BloqueCita key={c.id} cita={c} conflicto={conflicto} ini={enEje(c.inicio)} fin={enEje(c.fin)} onAbrir={onAbrir} />;
              })}

              {esHoy && ahora > desde && ahora < hasta && (
                <div className="cal-ahora" style={posicion(ahora - desde, 0)} aria-hidden="true" />
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

type BloqueCitaProps = Readonly<{
  cita: CitaVista;
  conflicto: boolean;
  ini: number;
  fin: number;
  onAbrir: (cita: CitaVista, conflicto: boolean) => void;
}>;

function BloqueCita({ cita, conflicto, ini, fin, onAbrir }: BloqueCitaProps) {
  const etiqueta = conflicto ? "Conflicto" : ESTADO_NOMBRE[cita.estado];
  return (
    <button
      type="button"
      className="cita"
      data-estado={cita.estado}
      data-conflicto={conflicto || undefined}
      data-corta={fin - ini < 25 || undefined}
      style={posicion(ini, fin - ini)}
      aria-label={`${hora(cita.inicio)} a ${hora(cita.fin)}, ${cita.paciente}, ${cita.servicio}, ${etiqueta}. Abrir detalle`}
      onClick={() => onAbrir(cita, conflicto)}
    >
      <span className="cita-linea">
        <time dateTime={cita.inicio}>{hora(cita.inicio)}</time>
        <strong>{cita.paciente}</strong>
        <span className="cita-estado">{etiqueta}</span>
      </span>
      <span className="cita-detalle">{cita.servicio}</span>
    </button>
  );
}
