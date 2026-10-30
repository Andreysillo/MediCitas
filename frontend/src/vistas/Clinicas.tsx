import { useState } from "react";
import { ZONAS_HORARIAS, crearClinica, listarClinicas } from "../api";
import Dialogo from "../componentes/Dialogo";
import { mensajeDe, useDatos } from "../hooks";
import "./admin.css";

// "Clínica Los Álamos" -> "clinica-los-alamos"
const aIdentificador = (nombre: string) =>
  nombre
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

export default function Clinicas() {
  const clinicas = useDatos(listarClinicas);
  const [nueva, setNueva] = useState(false);
  const [aviso, setAviso] = useState("");

  return (
    <div className="vista">
      <div className="barra">
        <p className="panel-nota">
          Desde aquí solo se dan de alta clínicas. El administrador de plataforma no accede a los datos clínicos de ninguna de ellas.
        </p>
        <button type="button" className="btn btn-cta" onClick={() => setNueva(true)}>
          Nueva clínica
        </button>
      </div>

      {aviso && <p className="aviso aviso-ok" role="status">{aviso}</p>}
      {clinicas.error && <p className="aviso aviso-error" role="alert">{clinicas.error}</p>}

      <section className="panel" aria-label="Clínicas">
        <div className="tabla-scroll">
          <table className="tabla">
            <thead>
              <tr>
                <th>Clínica</th>
                <th>Identificador</th>
                <th>Zona horaria</th>
                <th className="num">Usuarios activos</th>
              </tr>
            </thead>
            <tbody>
              {clinicas.datos?.map((c) => (
                <tr key={c.id}>
                  <td><strong>{c.nombre}</strong></td>
                  <td>{c.identificador}</td>
                  <td>{c.zona_horaria}</td>
                  <td className="num">{c.usuarios}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {nueva && (
        <Dialogo titulo="Nueva clínica" onCerrar={() => setNueva(false)}>
          {(cerrar) => (
            <FormularioClinica
              onCreada={(nombre, admin) => {
                setAviso(`${nombre} quedó creada con ${admin} como administrador. Ya aparece en "Ver como".`);
                clinicas.recargar();
                cerrar();
              }}
              onCancelar={cerrar}
            />
          )}
        </Dialogo>
      )}
    </div>
  );
}

type Props = Readonly<{ onCreada: (nombre: string, admin: string) => void; onCancelar: () => void }>;

function FormularioClinica({ onCreada, onCancelar }: Props) {
  const [nombre, setNombre] = useState("");
  const [identificador, setIdentificador] = useState("");
  // Mientras no se edite a mano, el identificador se sugiere a partir del nombre.
  const [identificadorManual, setIdentificadorManual] = useState(false);
  const [zona, setZona] = useState<string>(ZONAS_HORARIAS[0]);
  const [admin, setAdmin] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setEnviando(true);
    setError("");
    try {
      const r = await crearClinica({ nombre, identificador, zona_horaria: zona, admin_nombre: admin });
      onCreada(r.clinica.nombre, r.admin.nombre);
    } catch (err) {
      setError(mensajeDe(err));
      setEnviando(false);
    }
  }

  return (
    <form className="acciones" onSubmit={guardar}>
      <label className="field">
        <span>Nombre de la clínica</span>
        <input
          required
          autoComplete="off"
          value={nombre}
          onChange={(e) => {
            setNombre(e.target.value);
            if (!identificadorManual) setIdentificador(aIdentificador(e.target.value));
          }}
        />
      </label>
      <div className="campos-2">
        <label className="field">
          <span>Identificador</span>
          <input
            required
            autoComplete="off"
            value={identificador}
            onChange={(e) => {
              setIdentificador(e.target.value);
              setIdentificadorManual(true);
            }}
          />
        </label>
        <label className="field">
          <span>Zona horaria</span>
          <select value={zona} onChange={(e) => setZona(e.target.value)}>
            {ZONAS_HORARIAS.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="field">
        <span>Primer administrador de la clínica</span>
        <input required autoComplete="off" placeholder="Nombre completo" value={admin} onChange={(e) => setAdmin(e.target.value)} />
      </label>
      <p className="ayuda">La clínica y su administrador se crean juntos. Sus credenciales las emitirá Keycloak.</p>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="fila">
        <button type="button" className="btn" onClick={onCancelar}>Cancelar</button>
        <button type="submit" className="btn btn-cta" disabled={enviando}>{enviando ? "Creando…" : "Crear clínica"}</button>
      </div>
    </form>
  );
}
