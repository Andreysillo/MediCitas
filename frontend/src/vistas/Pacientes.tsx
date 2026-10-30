import { useEffect, useRef, useState } from "react";
import {
  historialPaciente,
  listarPacientes,
  obtenerPaciente,
  type CitaHistorial,
  type PacienteLista,
  type Sesion,
} from "../api";
import { ESTADO_NOMBRE, ROLES_QUE_EDITAN_PACIENTES, type Paciente } from "../api/dominio";
import { edad, fechaCompleta, fechaLocal, hora } from "../fechas";
import FormularioPaciente from "./FormularioPaciente";
import "./pacientes.css";

type Ficha = { paciente: Paciente; historial: CitaHistorial[] };

type Props = Readonly<{ sesion: Sesion }>;

export default function Pacientes({ sesion }: Props) {
  // El profesional solo lee (matriz de permisos): no ve los botones de alta ni de edición.
  const puedeEditar = ROLES_QUE_EDITAN_PACIENTES.includes(sesion.usuario.rol);
  const [texto, setTexto] = useState("");
  const [lista, setLista] = useState<{ total: number; pacientes: PacienteLista[] } | null>(null);
  const [version, setVersion] = useState(0);
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [abriendo, setAbriendo] = useState<string | null>(null);
  const [formulario, setFormulario] = useState<"nuevo" | "editar" | null>(null);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  // Número de la última ficha pedida: si llegan dos respuestas, solo cuenta la más reciente.
  const pedido = useRef(0);

  useEffect(() => {
    let vigente = true;
    listarPacientes(texto)
      .then((l) => vigente && setLista(l))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [texto, version]);

  // Se abre desde el clic y no desde un efecto a propósito: leer la ficha queda en la bitácora
  // (RF18), y un efecto se ejecuta dos veces en desarrollo y dejaría dos registros por lectura.
  async function abrir(id: string) {
    const mio = ++pedido.current;
    setAbriendo(id);
    setError("");
    setAviso("");
    if (window.matchMedia("(max-width: 1000px)").matches) window.scrollTo({ top: 0 });
    try {
      const [paciente, historial] = await Promise.all([obtenerPaciente(id), historialPaciente(id)]);
      if (mio === pedido.current) setFicha({ paciente, historial });
    } catch (e) {
      if (mio === pedido.current) setError(e instanceof Error ? e.message : "Error inesperado");
    } finally {
      if (mio === pedido.current) setAbriendo(null);
    }
  }

  function guardado(p: Paciente) {
    // Tras guardar no se vuelve a leer la ficha: el servidor ya devolvió los datos y así no se agrega una lectura a la bitácora.
    setFicha((f) => ({ paciente: p, historial: formulario === "editar" && f ? f.historial : [] }));
    setAviso(formulario === "editar" ? "Datos actualizados." : `${p.nombre} quedó registrado.`);
    setVersion((v) => v + 1);
  }

  return (
    <div className="pacientes" data-vista={ficha || abriendo ? "detalle" : "lista"}>
      <section className="pacientes-lista" aria-label="Lista de pacientes">
        <div className="lista-barra">
          <label className="field">
            <span>Buscar paciente</span>
            <input type="search" autoComplete="off" placeholder="Nombre o identificación" value={texto} onChange={(e) => setTexto(e.target.value)} />
          </label>
          {puedeEditar && (
            <button type="button" className="btn btn-cta" onClick={() => setFormulario("nuevo")}>
              Nuevo paciente
            </button>
          )}
        </div>

        {lista && lista.pacientes.length > 0 && (
          <ul className="lista">
            {lista.pacientes.map((p) => (
              <li key={p.id}>
                <button type="button" className="paciente-fila" aria-current={ficha?.paciente.id === p.id || abriendo === p.id} onClick={() => abrir(p.id)}>
                  <strong>{p.nombre}</strong>
                  <span>
                    {p.identificacion} · {edad(p.fecha_nacimiento)} años
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {lista?.pacientes.length === 0 && <p className="aviso">Ningún paciente coincide con la búsqueda.</p>}
        {lista && lista.total > lista.pacientes.length && (
          <p className="ayuda">
            Mostrando {lista.pacientes.length} de {lista.total}. Escribe más para afinar la búsqueda.
          </p>
        )}
      </section>

      <section className="ficha-col" aria-label="Ficha del paciente" aria-busy={abriendo !== null}>
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
        {ficha ? (
          <FichaPaciente ficha={ficha} puedeEditar={puedeEditar} onEditar={() => setFormulario("editar")} onVolver={() => setFicha(null)} />
        ) : (
          <div className="placeholder">{abriendo ? "Abriendo la ficha…" : "Elige un paciente para ver sus datos y su historial de citas."}</div>
        )}
      </section>

      {formulario && (
        <FormularioPaciente
          paciente={formulario === "editar" ? ficha?.paciente : undefined}
          onCerrar={() => setFormulario(null)}
          onGuardado={guardado}
        />
      )}
    </div>
  );
}

type FichaProps = Readonly<{ ficha: Ficha; puedeEditar: boolean; onEditar: () => void; onVolver: () => void }>;

function FichaPaciente({ ficha: { paciente: p, historial }, puedeEditar, onEditar, onVolver }: FichaProps) {
  return (
    <article className="ficha" aria-labelledby="ficha-nombre">
      <button type="button" className="btn volver" onClick={onVolver}>
        ‹ Pacientes
      </button>

      <header className="ficha-head">
        <div>
          <h2 id="ficha-nombre">{p.nombre}</h2>
          <p>
            {p.identificacion} · {edad(p.fecha_nacimiento)} años · nació el {fechaCompleta(p.fecha_nacimiento)}
          </p>
        </div>
        {puedeEditar && (
          <button type="button" className="btn" onClick={onEditar}>
            Editar datos
          </button>
        )}
      </header>

      <section aria-labelledby="ficha-contacto">
        <h3 id="ficha-contacto">Contacto</h3>
        <dl className="datos">
          <div>
            <dt>Teléfono</dt>
            <dd>{p.telefono ? <a href={`tel:${p.telefono}`}>{p.telefono}</a> : "—"}</dd>
          </div>
          <div>
            <dt>Correo</dt>
            <dd>{p.correo ? <a href={`mailto:${p.correo}`}>{p.correo}</a> : "—"}</dd>
          </div>
        </dl>
        <p className="ayuda">Haber abierto esta ficha quedó registrado en la bitácora de auditoría (RF18).</p>
      </section>

      <section aria-labelledby="ficha-historial">
        <h3 id="ficha-historial">Historial de citas ({historial.length})</h3>
        {historial.length === 0 ? (
          <p className="ayuda">Este paciente todavía no tiene citas.</p>
        ) : (
          <ol className="historial">
            {historial.map((c) => (
              <li key={c.id} data-estado={c.estado}>
                <div>
                  <strong>{c.servicio}</strong>
                  <span>
                    {fechaCompleta(fechaLocal(new Date(c.inicio)))}, {hora(c.inicio)} · {c.profesional}
                  </span>
                </div>
                <span className="estado-pill" data-estado={c.estado}>
                  {ESTADO_NOMBRE[c.estado]}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  );
}
