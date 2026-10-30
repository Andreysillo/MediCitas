import { useState } from "react";
import {
  actualizarProfesional,
  actualizarServicio,
  crearEspecialidad,
  crearProfesional,
  crearServicio,
  listarEspecialidades,
  listarProfesionalesAdmin,
  listarServiciosAdmin,
  usuariosProfesionalesLibres,
  type ProfesionalAdmin,
  type ServicioAdmin,
} from "../api";
import type { Especialidad } from "../api/dominio";
import Dialogo from "../componentes/Dialogo";
import { mensajeDe, useDatos } from "../hooks";
import "./admin.css";

type Pestana = "servicios" | "profesionales" | "especialidades";

const PESTANAS: { id: Pestana; nombre: string }[] = [
  { id: "servicios", nombre: "Servicios" },
  { id: "profesionales", nombre: "Profesionales" },
  { id: "especialidades", nombre: "Especialidades" },
];

export default function Catalogo() {
  const [pestana, setPestana] = useState<Pestana>("servicios");
  return (
    <div className="vista">
      <div className="pestanas" role="group" aria-label="Secciones del catálogo">
        {PESTANAS.map((p) => (
          <button key={p.id} type="button" aria-pressed={pestana === p.id} onClick={() => setPestana(p.id)}>
            {p.nombre}
          </button>
        ))}
      </div>
      {pestana === "servicios" && <Servicios />}
      {pestana === "profesionales" && <Profesionales />}
      {pestana === "especialidades" && <Especialidades />}
    </div>
  );
}

// ---------- Especialidades ----------

function Especialidades() {
  const lista = useDatos(listarEspecialidades);
  const [nombre, setNombre] = useState("");
  const [error, setError] = useState("");

  async function agregar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setError("");
    try {
      await crearEspecialidad(nombre);
      setNombre("");
      lista.recargar();
    } catch (err) {
      setError(mensajeDe(err));
    }
  }

  return (
    <section className="panel" aria-labelledby="h-esp">
      <h2 id="h-esp">Especialidades</h2>
      <p className="panel-nota">Cada clínica mantiene las suyas: no hay un catálogo global. Un servicio y un profesional solo pueden usar especialidades de su propia clínica.</p>
      {lista.datos?.length === 0 && <p className="panel-nota">Todavía no hay especialidades. Crea la primera para poder definir servicios.</p>}
      <ul className="chips">
        {lista.datos?.map((e) => (
          <li key={e.id} className="etiqueta">
            {e.nombre}
          </li>
        ))}
      </ul>
      <form className="barra" onSubmit={agregar}>
        <label className="field">
          <span>Nueva especialidad</span>
          <input required value={nombre} autoComplete="off" onChange={(e) => setNombre(e.target.value)} />
        </label>
        <button type="submit" className="btn">
          Agregar
        </button>
      </form>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
    </section>
  );
}

// ---------- Servicios ----------

function Servicios() {
  const servicios = useDatos(listarServiciosAdmin);
  const especialidades = useDatos(listarEspecialidades);
  const [dialogo, setDialogo] = useState<"nuevo" | ServicioAdmin | null>(null);
  const [error, setError] = useState("");

  async function alternar(s: ServicioAdmin) {
    setError("");
    try {
      await actualizarServicio(s.id, { nombre: s.nombre, duracion_minutos: s.duracion_minutos, activo: !s.activo });
      servicios.recargar();
    } catch (e) {
      setError(mensajeDe(e));
    }
  }

  const sinEspecialidades = especialidades.datos?.length === 0;

  return (
    <section className="panel" aria-labelledby="h-serv">
      <div className="barra">
        <h2 id="h-serv" className="panel-titulo">Servicios</h2>
        <button type="button" className="btn btn-cta" disabled={sinEspecialidades} onClick={() => setDialogo("nuevo")}>
          Nuevo servicio
        </button>
      </div>
      <p className="panel-nota">
        La duración define el espacio que ocupa la cita. Cambiarla afecta solo a las citas nuevas: las ya reservadas conservan su duración (I4).
      </p>
      {sinEspecialidades && <p className="aviso">Crea primero una especialidad en la pestaña Especialidades.</p>}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {servicios.datos && servicios.datos.length > 0 && (
        <div className="tabla-scroll">
          <table className="tabla">
            <thead>
              <tr>
                <th>Servicio</th>
                <th>Especialidad</th>
                <th className="num">Duración</th>
                <th>Estado</th>
                <th aria-label="Acciones" />
              </tr>
            </thead>
            <tbody>
              {servicios.datos.map((s) => (
                <tr key={s.id} className={s.activo ? "" : "tenue"}>
                  <td><strong>{s.nombre}</strong></td>
                  <td>{s.especialidad}</td>
                  <td className="num">{s.duracion_minutos} min</td>
                  <td>
                    <span className="etiqueta" data-tono={s.activo ? "ok" : "baja"}>{s.activo ? "Activo" : "Desactivado"}</span>
                  </td>
                  <td>
                    <div className="acciones-fila">
                      <button type="button" className="btn" onClick={() => setDialogo(s)}>Editar</button>
                      <button type="button" className="btn" onClick={() => alternar(s)}>{s.activo ? "Desactivar" : "Activar"}</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dialogo && especialidades.datos && (
        <Dialogo titulo={dialogo === "nuevo" ? "Nuevo servicio" : "Editar servicio"} onCerrar={() => setDialogo(null)}>
          {(cerrar) => (
            <FormularioServicio
              servicio={dialogo === "nuevo" ? undefined : dialogo}
              especialidades={especialidades.datos ?? []}
              onGuardado={() => {
                servicios.recargar();
                cerrar();
              }}
              onCancelar={cerrar}
            />
          )}
        </Dialogo>
      )}
    </section>
  );
}

type FormServicioProps = Readonly<{
  servicio?: ServicioAdmin;
  especialidades: Especialidad[];
  onGuardado: () => void;
  onCancelar: () => void;
}>;

function FormularioServicio({ servicio, especialidades, onGuardado, onCancelar }: FormServicioProps) {
  const [nombre, setNombre] = useState(servicio?.nombre ?? "");
  const [duracion, setDuracion] = useState(String(servicio?.duracion_minutos ?? 30));
  const [especialidadId, setEspecialidadId] = useState(servicio?.especialidad_id ?? especialidades[0]?.id ?? "");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setEnviando(true);
    setError("");
    try {
      if (servicio) {
        await actualizarServicio(servicio.id, { nombre, duracion_minutos: Number(duracion), activo: servicio.activo });
      } else {
        await crearServicio({ nombre, duracion_minutos: Number(duracion), especialidad_id: especialidadId });
      }
      onGuardado();
    } catch (err) {
      setError(mensajeDe(err));
      setEnviando(false);
    }
  }

  return (
    <form className="acciones" onSubmit={guardar}>
      <label className="field">
        <span>Nombre del servicio</span>
        <input required autoComplete="off" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      </label>
      <div className="campos-2">
        <label className="field">
          <span>Duración (minutos)</span>
          <input required type="number" min={5} max={480} step={5} value={duracion} onChange={(e) => setDuracion(e.target.value)} />
        </label>
        {servicio ? (
          <div className="field">
            <span>Especialidad</span>
            <strong>{servicio.especialidad}</strong>
          </div>
        ) : (
          <label className="field">
            <span>Especialidad requerida</span>
            <select value={especialidadId} onChange={(e) => setEspecialidadId(e.target.value)}>
              {especialidades.map((e) => (
                <option key={e.id} value={e.id}>{e.nombre}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="fila">
        <button type="button" className="btn" onClick={onCancelar}>Cancelar</button>
        <button type="submit" className="btn btn-cta" disabled={enviando}>{enviando ? "Guardando…" : "Guardar"}</button>
      </div>
    </form>
  );
}

// ---------- Profesionales ----------

function Profesionales() {
  const profesionales = useDatos(listarProfesionalesAdmin);
  const servicios = useDatos(listarServiciosAdmin);
  const especialidades = useDatos(listarEspecialidades);
  const libres = useDatos(usuariosProfesionalesLibres);
  const [dialogo, setDialogo] = useState<"nuevo" | ProfesionalAdmin | null>(null);

  const nombresServicios = (p: ProfesionalAdmin) =>
    servicios.datos?.filter((s) => p.servicios_ids.includes(s.id)).map((s) => s.nombre).join(", ") || "—";

  const listo = servicios.datos && especialidades.datos && libres.datos;

  return (
    <section className="panel" aria-labelledby="h-prof">
      <div className="barra">
        <h2 id="h-prof" className="panel-titulo">Profesionales</h2>
        <button type="button" className="btn btn-cta" disabled={!listo || libres.datos?.length === 0 || especialidades.datos?.length === 0} onClick={() => setDialogo("nuevo")}>
          Registrar profesional
        </button>
      </div>
      <p className="panel-nota">
        Un profesional atiende solo los servicios de su especialidad que se le habiliten. Para registrar uno nuevo, primero crea su usuario con rol Profesional.
      </p>
      {libres.datos?.length === 0 && <p className="panel-nota">No hay usuarios con rol Profesional sin registrar.</p>}

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr>
              <th>Profesional</th>
              <th>Especialidad</th>
              <th>Colegiado</th>
              <th>Servicios habilitados</th>
              <th aria-label="Acciones" />
            </tr>
          </thead>
          <tbody>
            {profesionales.datos?.map((p) => (
              <tr key={p.id} className={p.activo ? "" : "tenue"}>
                <td>
                  <strong>{p.nombre}</strong>
                  {!p.activo && <span className="panel-nota"> (de baja)</span>}
                </td>
                <td>{p.especialidad}</td>
                <td>{p.numero_colegiado}</td>
                <td>{nombresServicios(p)}</td>
                <td>
                  <div className="acciones-fila">
                    <button type="button" className="btn" disabled={!listo} onClick={() => setDialogo(p)}>Editar</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dialogo && listo && (
        <Dialogo titulo={dialogo === "nuevo" ? "Registrar profesional" : "Editar profesional"} onCerrar={() => setDialogo(null)}>
          {(cerrar) => (
            <FormularioProfesional
              profesional={dialogo === "nuevo" ? undefined : dialogo}
              libres={libres.datos ?? []}
              especialidades={especialidades.datos ?? []}
              servicios={servicios.datos ?? []}
              onGuardado={() => {
                profesionales.recargar();
                libres.recargar();
                cerrar();
              }}
              onCancelar={cerrar}
            />
          )}
        </Dialogo>
      )}
    </section>
  );
}

type FormProfProps = Readonly<{
  profesional?: ProfesionalAdmin;
  libres: { id: string; nombre: string }[];
  especialidades: Especialidad[];
  servicios: ServicioAdmin[];
  onGuardado: () => void;
  onCancelar: () => void;
}>;

function FormularioProfesional({ profesional, libres, especialidades, servicios, onGuardado, onCancelar }: FormProfProps) {
  const [usuarioId, setUsuarioId] = useState(libres[0]?.id ?? "");
  const [especialidadId, setEspecialidadId] = useState(profesional?.especialidad_id ?? especialidades[0]?.id ?? "");
  const [colegiado, setColegiado] = useState(profesional?.numero_colegiado ?? "");
  const [ids, setIds] = useState<string[]>(profesional?.servicios_ids ?? []);
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  // Solo se ofrecen los servicios de la especialidad elegida (regla de RF3 y RF4).
  const delaEspecialidad = servicios.filter((s) => s.especialidad_id === especialidadId);

  const alternar = (id: string) => setIds((actual) => (actual.includes(id) ? actual.filter((x) => x !== id) : [...actual, id]));

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setEnviando(true);
    setError("");
    const datos = { especialidad_id: especialidadId, numero_colegiado: colegiado, servicios_ids: ids };
    try {
      if (profesional) await actualizarProfesional(profesional.id, datos);
      else await crearProfesional({ ...datos, usuario_id: usuarioId });
      onGuardado();
    } catch (err) {
      setError(mensajeDe(err));
      setEnviando(false);
    }
  }

  return (
    <form className="acciones" onSubmit={guardar}>
      {profesional ? (
        <div className="field">
          <span>Profesional</span>
          <strong>{profesional.nombre}</strong>
        </div>
      ) : (
        <label className="field">
          <span>Usuario</span>
          <select value={usuarioId} onChange={(e) => setUsuarioId(e.target.value)}>
            {libres.map((u) => (
              <option key={u.id} value={u.id}>{u.nombre}</option>
            ))}
          </select>
        </label>
      )}
      <div className="campos-2">
        <label className="field">
          <span>Especialidad</span>
          <select
            value={especialidadId}
            onChange={(e) => {
              setEspecialidadId(e.target.value);
              setIds([]); // los servicios de la especialidad anterior ya no corresponden
            }}
          >
            {especialidades.map((e) => (
              <option key={e.id} value={e.id}>{e.nombre}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Número de colegiado</span>
          <input required autoComplete="off" value={colegiado} onChange={(e) => setColegiado(e.target.value)} />
        </label>
      </div>

      <fieldset className="casillas">
        <legend>Servicios que atiende</legend>
        {delaEspecialidad.length === 0 && <p className="ayuda">No hay servicios para esta especialidad. Créalos en la pestaña Servicios.</p>}
        {delaEspecialidad.map((s) => (
          <label key={s.id} className="casilla">
            <input type="checkbox" checked={ids.includes(s.id)} onChange={() => alternar(s.id)} />
            <span>{s.nombre}{!s.activo && " (desactivado)"}</span>
            <span>{s.duracion_minutos} min</span>
          </label>
        ))}
      </fieldset>

      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="fila">
        <button type="button" className="btn" onClick={onCancelar}>Cancelar</button>
        <button type="submit" className="btn btn-cta" disabled={enviando}>{enviando ? "Guardando…" : "Guardar"}</button>
      </div>
    </form>
  );
}
