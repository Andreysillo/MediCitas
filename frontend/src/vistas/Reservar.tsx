import { useEffect, useRef, useState, type RefObject } from "react";
import {
  ApiError,
  buscarPacientes,
  listarServicios,
  reservarCita,
  simularReservaAjena,
  type CitaVista,
  type PacienteResumen,
  type ServicioVista,
} from "../api";
import Espacios, { type Espacio } from "../componentes/Espacios";
import { fechaCorta, fechaLocal, hora } from "../fechas";
import "./reservar.css";

// Los tres desenlaces que el enunciado exige distinguir en la reserva.
type Resultado =
  | { tipo: "concedida"; cita: CitaVista; profesional: string }
  | { tipo: "tomado"; mensaje: string }
  | { tipo: "invalida"; mensaje: string };

export default function Reservar() {
  const [servicios, setServicios] = useState<ServicioVista[]>([]);
  const [servicioId, setServicioId] = useState("");
  const [version, setVersion] = useState(0);
  const [espacio, setEspacio] = useState<Espacio | null>(null);
  const [paciente, setPaciente] = useState<PacienteResumen | null>(null);
  const [competencia, setCompetencia] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const buscadorRef = useRef<HTMLInputElement>(null);

  const servicio = servicios.find((s) => s.id === servicioId);

  useEffect(() => {
    listarServicios().then(setServicios);
  }, []);

  function elegirServicio(id: string) {
    setServicioId(id);
    setEspacio(null);
    setResultado(null);
  }

  function elegirEspacio(e: Espacio) {
    setEspacio(e);
    setResultado(null);
    if (!paciente) buscadorRef.current?.focus();
  }

  async function reservar() {
    if (!espacio || !paciente || !servicio) return;
    const solicitud = {
      paciente_id: paciente.id,
      profesional_id: espacio.profesional.id,
      servicio_id: servicio.id,
      inicio: espacio.inicio,
    };
    setEnviando(true);
    try {
      if (competencia) simularReservaAjena(solicitud);
      const cita = await reservarCita(solicitud);
      setResultado({ tipo: "concedida", cita, profesional: espacio.profesional.nombre });
      setEspacio(null);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      const mensaje = e instanceof Error ? e.message : "Error inesperado";
      setResultado(status === 409 ? { tipo: "tomado", mensaje } : { tipo: "invalida", mensaje });
      if (status === 409) setEspacio(null);
    } finally {
      setEnviando(false);
      setVersion((v) => v + 1);
    }
  }

  function reservarOtra() {
    setResultado(null);
    setPaciente(null);
  }

  // Servicios agrupados por especialidad, en el orden en que llegan.
  const grupos = new Map<string, ServicioVista[]>();
  for (const s of servicios) grupos.set(s.especialidad, [...(grupos.get(s.especialidad) ?? []), s]);

  const faltan = [!servicio && "servicio", !espacio && "horario", !paciente && "paciente"].filter(Boolean).join(", ");

  return (
    <div className="reservar">
      <div className="reservar-pasos">
        <section className="paso" aria-labelledby="paso-1">
          <EncabezadoPaso numero="01" id="paso-1" titulo="¿Qué servicio?" ayuda="Su duración define cuánto espacio ocupa la cita." />
          <div className="servicios">
            {[...grupos].map(([especialidad, lista]) => (
              <fieldset key={especialidad} className="servicio-grupo">
                <legend>{especialidad}</legend>
                {lista.map((s) => (
                  <label key={s.id} className="opcion">
                    <input type="radio" name="servicio" className="sr-only" checked={servicioId === s.id} onChange={() => elegirServicio(s.id)} />
                    <span className="opcion-nombre">{s.nombre}</span>
                    <span className="opcion-meta">{s.duracion_minutos} min</span>
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
        </section>

        <section className="paso" aria-labelledby="paso-2">
          <EncabezadoPaso numero="02" id="paso-2" titulo="¿Cuándo y con quién?" ayuda="Espacios libres de la semana, por profesional." />
          {servicio ? (
            <Espacios servicioId={servicio.id} elegido={espacio} onElegir={elegirEspacio} version={version} />
          ) : (
            <p className="aviso">Elige un servicio para ver los espacios disponibles.</p>
          )}
        </section>
      </div>

      <aside className="paso reservar-resumen" aria-labelledby="paso-3">
        <EncabezadoPaso numero="03" id="paso-3" titulo="¿Para qué paciente?" ayuda="Busca por nombre o identificación." />
        <BuscadorPaciente paciente={paciente} onElegir={setPaciente} inputRef={buscadorRef} />

        {servicio && espacio && (
          // key: al cambiar de espacio el resumen se monta de nuevo y repite su entrada.
          <dl className="ticket" key={espacio.inicio + espacio.profesional.id}>
            <div>
              <dt>Servicio</dt>
              <dd>
                {servicio.nombre} · {servicio.duracion_minutos} min
              </dd>
            </div>
            <div>
              <dt>Profesional</dt>
              <dd>{espacio.profesional.nombre}</dd>
            </div>
            <div>
              <dt>Cuándo</dt>
              <dd>
                {fechaCorta(fechaLocal(new Date(espacio.inicio)))}, {hora(espacio.inicio)} a{" "}
                {hora(new Date(Date.parse(espacio.inicio) + servicio.duracion_minutos * 60_000).toISOString())}
              </dd>
            </div>
          </dl>
        )}

        <label className="demo">
          <input type="checkbox" checked={competencia} onChange={(e) => setCompetencia(e.target.checked)} />
          <span>
            <strong>Simular otra recepcionista</strong>
            Demostración: alguien toma el mismo espacio justo antes de que confirmes.
          </span>
        </label>

        <button type="button" className="btn btn-cta btn-bloque" disabled={!servicio || !espacio || !paciente || enviando} onClick={reservar}>
          {enviando ? "Reservando…" : "Reservar cita"}
        </button>
        {faltan && !resultado && <p className="falta">Falta elegir: {faltan}.</p>}

        {resultado && <Desenlace resultado={resultado} onOtra={reservarOtra} />}
      </aside>
    </div>
  );
}

type EncabezadoProps = Readonly<{ numero: string; id: string; titulo: string; ayuda: string }>;

function EncabezadoPaso({ numero, id, titulo, ayuda }: EncabezadoProps) {
  return (
    <header className="paso-head">
      <span className="paso-num" aria-hidden="true">
        {numero}
      </span>
      <div>
        <h2 id={id}>{titulo}</h2>
        <p>{ayuda}</p>
      </div>
    </header>
  );
}

type BuscadorProps = Readonly<{
  paciente: PacienteResumen | null;
  onElegir: (p: PacienteResumen | null) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}>;

function BuscadorPaciente({ paciente, onElegir, inputRef }: BuscadorProps) {
  const [texto, setTexto] = useState("");
  const [encontrados, setEncontrados] = useState<PacienteResumen[]>([]);

  useEffect(() => {
    let vigente = true;
    buscarPacientes(texto).then((r) => vigente && setEncontrados(r));
    return () => {
      vigente = false;
    };
  }, [texto]);

  if (paciente) {
    return (
      <div className="paciente-elegido">
        <div>
          <strong>{paciente.nombre}</strong>
          <span>{paciente.identificacion}</span>
        </div>
        <button type="button" className="btn" onClick={() => onElegir(null)}>
          Cambiar
        </button>
      </div>
    );
  }

  return (
    <div className="buscador">
      <label className="field">
        <span>Nombre o identificación</span>
        <input
          ref={inputRef}
          type="search"
          autoComplete="off"
          placeholder="Ej. María o 1-0234"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
        />
      </label>
      {encontrados.length > 0 && (
        <ul className="encontrados">
          {encontrados.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => {
                  onElegir(p);
                  setTexto("");
                }}
              >
                <strong>{p.nombre}</strong>
                <span>{p.identificacion}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Desenlace({ resultado, onOtra }: Readonly<{ resultado: Resultado; onOtra: () => void }>) {
  if (resultado.tipo === "concedida") {
    const { cita, profesional } = resultado;
    return (
      <div className="desenlace desenlace-ok" role="status">
        <strong>Cita reservada</strong>
        <p>
          {cita.paciente} con {profesional}, {fechaCorta(fechaLocal(new Date(cita.inicio)))} de {hora(cita.inicio)} a {hora(cita.fin)}.
        </p>
        <div className="desenlace-acciones">
          <a className="btn" href="#/agenda">
            Ver agenda
          </a>
          <button type="button" className="btn" onClick={onOtra}>
            Reservar otra
          </button>
        </div>
      </div>
    );
  }
  if (resultado.tipo === "tomado") {
    return (
      <div className="desenlace desenlace-tomado" role="alert">
        <strong>Espacio ya tomado</strong>
        <p>{resultado.mensaje}. Los horarios ya están actualizados: elige otro.</p>
      </div>
    );
  }
  return (
    <div className="desenlace desenlace-error" role="alert">
      <strong>No se pudo reservar</strong>
      <p>{resultado.mensaje}.</p>
    </div>
  );
}
