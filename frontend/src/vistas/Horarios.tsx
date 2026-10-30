import { useEffect, useState } from "react";
import {
  crearBloqueo,
  crearHorario,
  eliminarBloqueo,
  eliminarHorario,
  listarBloqueos,
  listarHorarios,
  profesionalesGestionables,
  type CitaVista,
} from "../api";
import { fechaCorta, fechaLocal, hora } from "../fechas";
import { mensajeDe, useDatos } from "../hooks";
import "./admin.css";
import "./horarios.css";

const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

type Aviso = { tipo: "ok" | "alerta"; texto: string; citas?: CitaVista[] };

const cuando = (inicio: string) => `${fechaCorta(fechaLocal(new Date(inicio)))}, ${hora(inicio)}`;

export default function Horarios() {
  const profesionales = useDatos(profesionalesGestionables);
  const [profesionalId, setProfesionalId] = useState("");
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [error, setError] = useState("");

  // Por defecto, el primer profesional de la lista (para un profesional, es él mismo).
  useEffect(() => {
    if (!profesionalId && profesionales.datos?.length) setProfesionalId(profesionales.datos[0].id);
  }, [profesionales.datos, profesionalId]);

  const horarios = useDatos(() => (profesionalId ? listarHorarios(profesionalId) : Promise.resolve([])), [profesionalId]);
  const bloqueos = useDatos(() => (profesionalId ? listarBloqueos(profesionalId) : Promise.resolve([])), [profesionalId]);

  // Formularios
  const [dia, setDia] = useState(1);
  const [desde, setDesde] = useState("08:00");
  const [hasta, setHasta] = useState("12:00");
  const [motivo, setMotivo] = useState("");
  const [inicio, setInicio] = useState("");
  const [fin, setFin] = useState("");

  async function accion(hacer: () => Promise<void>) {
    setError("");
    setAviso(null);
    try {
      await hacer();
    } catch (e) {
      setError(mensajeDe(e));
    }
  }

  const agregarHorario = (e: { preventDefault: () => void }) => {
    e.preventDefault();
    return accion(async () => {
      await crearHorario(profesionalId, { dia_semana: dia, hora_inicio: desde, hora_fin: hasta });
      horarios.recargar();
    });
  };

  const quitarHorario = (id: string) =>
    accion(async () => {
      const { conflictos } = await eliminarHorario(id);
      horarios.recargar();
      setAviso(
        conflictos.length
          ? { tipo: "alerta", texto: `${conflictos.length} cita(s) reservada(s) quedaron fuera del horario. Recepción debe reprogramarlas (I3).`, citas: conflictos }
          : { tipo: "ok", texto: "Bloque quitado. El cambio rige hacia adelante." },
      );
    });

  const agregarBloqueo = (e: { preventDefault: () => void }) => {
    e.preventDefault();
    return accion(async () => {
      // El campo datetime-local entrega hora local sin zona; Date la interpreta como local y la pasa a instante.
      const b = await crearBloqueo(profesionalId, { inicio: new Date(inicio).toISOString(), fin: new Date(fin).toISOString(), motivo });
      bloqueos.recargar();
      setMotivo("");
      setAviso(
        b.conflictos.length
          ? { tipo: "alerta", texto: `Bloqueo registrado. ${b.conflictos.length} cita(s) reservada(s) caen dentro y no se cancelaron: recepción debe reprogramarlas (RF6).`, citas: b.conflictos }
          : { tipo: "ok", texto: "Bloqueo registrado. No hay citas reservadas dentro de ese rango." },
      );
    });
  };

  const quitarBloqueo = (id: string) =>
    accion(async () => {
      await eliminarBloqueo(id);
      bloqueos.recargar();
      setAviso({ tipo: "ok", texto: "Bloqueo eliminado: la disponibilidad vuelve a abrirse." });
    });

  if (profesionales.error) return <p className="aviso aviso-error" role="alert">{profesionales.error}</p>;
  if (!profesionales.datos) return <p className="aviso">Cargando…</p>;
  if (profesionales.datos.length === 0) return <p className="aviso">No hay profesionales registrados en la clínica.</p>;

  const solo = profesionales.datos.length === 1;

  return (
    <div className="vista">
      <div className="barra">
        {solo ? (
          <p className="panel-nota">
            Horario de <strong>{profesionales.datos[0].nombre}</strong>
          </p>
        ) : (
          <label className="field">
            <span>Profesional</span>
            <select value={profesionalId} onChange={(e) => { setProfesionalId(e.target.value); setAviso(null); setError(""); }}>
              {profesionales.datos.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre} · {p.especialidad}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {aviso && (
        <div className={`aviso ${aviso.tipo === "ok" ? "aviso-ok" : "aviso-conflicto"}`} role="status">
          <p>{aviso.texto}</p>
          {aviso.citas && (
            <ul className="conflictos">
              {aviso.citas.map((c) => (
                <li key={c.id}>
                  {cuando(c.inicio)} · {c.paciente} · {c.servicio}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}

      <section className="panel" aria-labelledby="h-semanal">
        <h2 id="h-semanal">Horario semanal</h2>
        <p className="panel-nota">
          Las horas son locales de la clínica. Un día puede tener varios bloques (jornada partida). Un cambio rige hacia adelante y no cancela citas.
        </p>
        <ul className="semana-horario">
          {DIAS.map((nombre, i) => {
            const bloques = horarios.datos?.filter((h) => h.dia_semana === i + 1) ?? [];
            return (
              <li key={nombre}>
                <strong>{nombre}</strong>
                {bloques.length === 0 ? (
                  <span className="sin-atencion">No atiende</span>
                ) : (
                  <ul>
                    {bloques.map((h) => (
                      <li key={h.id} className="bloque">
                        {h.hora_inicio} – {h.hora_fin}
                        <button type="button" className="btn btn-peligro" aria-label={`Quitar bloque ${h.hora_inicio} a ${h.hora_fin} del ${nombre}`} onClick={() => quitarHorario(h.id)}>
                          Quitar
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>

        <form className="barra" onSubmit={agregarHorario}>
          <label className="field">
            <span>Día</span>
            <select value={dia} onChange={(e) => setDia(Number(e.target.value))}>
              {DIAS.map((nombre, i) => (
                <option key={nombre} value={i + 1}>
                  {nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Desde</span>
            <input type="time" required value={desde} onChange={(e) => setDesde(e.target.value)} />
          </label>
          <label className="field">
            <span>Hasta</span>
            <input type="time" required value={hasta} onChange={(e) => setHasta(e.target.value)} />
          </label>
          <button type="submit" className="btn">
            Agregar bloque
          </button>
        </form>
      </section>

      <section className="panel" aria-labelledby="h-bloqueos">
        <h2 id="h-bloqueos">Bloqueos de agenda</h2>
        <p className="panel-nota">Vacaciones o permisos. Retiran la disponibilidad hacia adelante; las citas ya reservadas dentro del rango se listan como conflicto.</p>

        {bloqueos.datos?.length === 0 && <p className="panel-nota">No hay bloqueos vigentes ni futuros.</p>}
        {bloqueos.datos && bloqueos.datos.length > 0 && (
          <ul className="lista-bloqueos">
            {bloqueos.datos.map((b) => (
              <li key={b.id}>
                <div>
                  <strong>{b.motivo}</strong>
                  <span>
                    {cuando(b.inicio)} → {cuando(b.fin)}
                  </span>
                </div>
                {b.conflictos.length > 0 && <span className="etiqueta" data-tono="escritura">{b.conflictos.length} en conflicto</span>}
                <button type="button" className="btn btn-peligro" aria-label={`Eliminar bloqueo ${b.motivo}`} onClick={() => quitarBloqueo(b.id)}>
                  Eliminar
                </button>
              </li>
            ))}
          </ul>
        )}

        <form className="campos-2" onSubmit={agregarBloqueo}>
          <label className="field" style={{ gridColumn: "1 / -1" }}>
            <span>Motivo</span>
            <input required value={motivo} maxLength={200} placeholder="Vacaciones, permiso, congreso…" onChange={(e) => setMotivo(e.target.value)} />
          </label>
          <label className="field">
            <span>Inicio</span>
            <input type="datetime-local" required value={inicio} onChange={(e) => setInicio(e.target.value)} />
          </label>
          <label className="field">
            <span>Fin</span>
            <input type="datetime-local" required value={fin} onChange={(e) => setFin(e.target.value)} />
          </label>
          <div>
            <button type="submit" className="btn">
              Registrar bloqueo
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
