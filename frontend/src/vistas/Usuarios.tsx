import { useState } from "react";
import { ROLES_ASIGNABLES, cambiarActivo, cambiarRol, crearUsuario, listarUsuarios } from "../api";
import type { Rol } from "../api/dominio";
import Dialogo from "../componentes/Dialogo";
import { mensajeDe, useDatos } from "../hooks";
import { ROL_NOMBRE } from "../navigation";
import "./admin.css";

export default function Usuarios() {
  const usuarios = useDatos(listarUsuarios);
  const [nuevo, setNuevo] = useState(false);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");

  async function accion(hacer: () => Promise<string>) {
    setError("");
    setAviso("");
    try {
      setAviso(await hacer());
      usuarios.recargar();
    } catch (e) {
      setError(mensajeDe(e));
    }
  }

  const cambiarElRol = (id: string, rol: Rol) => accion(async () => {
    await cambiarRol(id, rol);
    return "Rol actualizado.";
  });

  const darDeBaja = (id: string) => accion(async () => {
    const { citas_pendientes } = await cambiarActivo(id, false);
    return citas_pendientes > 0
      ? `Usuario dado de baja. Tiene ${citas_pendientes} cita(s) reservada(s) pendiente(s): recepción debe reprogramarlas.`
      : "Usuario dado de baja. Su acceso se corta en la próxima solicitud.";
  });

  const reactivar = (id: string) => accion(async () => {
    await cambiarActivo(id, true);
    return "Usuario reactivado.";
  });

  return (
    <div className="vista">
      <div className="barra">
        <p className="panel-nota">
          Las credenciales las administra Keycloak: aquí solo se decide quién pertenece a la clínica y con qué rol. Nada se borra; la baja es lógica.
        </p>
        <button type="button" className="btn btn-cta" onClick={() => setNuevo(true)}>
          Nuevo usuario
        </button>
      </div>

      {aviso && <p className="aviso aviso-ok" role="status">{aviso}</p>}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {usuarios.error && <p className="aviso aviso-error" role="alert">{usuarios.error}</p>}

      <section className="panel" aria-label="Usuarios de la clínica">
        <div className="tabla-scroll">
          <table className="tabla">
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Rol</th>
                <th>Estado</th>
                <th aria-label="Acciones" />
              </tr>
            </thead>
            <tbody>
              {usuarios.datos?.map((u) => (
                <tr key={u.id} className={u.activo ? "" : "tenue"}>
                  <td>
                    <strong>{u.nombre}</strong>
                    {u.yo && <span className="panel-nota"> (tú)</span>}
                  </td>
                  <td>
                    <select
                      aria-label={`Rol de ${u.nombre}`}
                      value={u.rol}
                      // No se cambia el propio rol ni el de un profesional registrado: la API también lo rechaza.
                      disabled={u.yo || u.es_profesional || !u.activo}
                      onChange={(e) => cambiarElRol(u.id, e.target.value as Rol)}
                    >
                      {ROLES_ASIGNABLES.map((r) => (
                        <option key={r} value={r}>
                          {ROL_NOMBRE[r]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <span className="etiqueta" data-tono={u.activo ? "ok" : "baja"}>
                      {u.activo ? "Activo" : "De baja"}
                    </span>
                  </td>
                  <td>
                    <div className="acciones-fila">
                      {u.activo ? (
                        <button type="button" className="btn btn-peligro" disabled={u.yo} onClick={() => darDeBaja(u.id)}>
                          Dar de baja
                        </button>
                      ) : (
                        <button type="button" className="btn" onClick={() => reactivar(u.id)}>
                          Reactivar
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {nuevo && (
        <Dialogo titulo="Nuevo usuario" onCerrar={() => setNuevo(false)}>
          {(cerrar) => (
            <FormularioUsuario
              onCreado={(nombre) => {
                setAviso(`${nombre} quedó registrado. Ya aparece en "Ver como".`);
                usuarios.recargar();
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

type FormProps = Readonly<{ onCreado: (nombre: string) => void; onCancelar: () => void }>;

function FormularioUsuario({ onCreado, onCancelar }: FormProps) {
  const [nombre, setNombre] = useState("");
  const [rol, setRol] = useState<Rol>("RECEPCION");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setEnviando(true);
    setError("");
    try {
      const u = await crearUsuario({ nombre, rol });
      onCreado(u.nombre);
    } catch (err) {
      setError(mensajeDe(err));
      setEnviando(false);
    }
  }

  return (
    <form className="acciones" onSubmit={guardar}>
      <label className="field">
        <span>Nombre completo</span>
        <input required autoComplete="off" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      </label>
      <label className="field">
        <span>Rol</span>
        <select value={rol} onChange={(e) => setRol(e.target.value as Rol)}>
          {ROLES_ASIGNABLES.map((r) => (
            <option key={r} value={r}>
              {ROL_NOMBRE[r]}
            </option>
          ))}
        </select>
      </label>
      {rol === "PROFESIONAL" && <p className="ayuda">Después, regístralo como profesional en Catálogo para asignarle especialidad y servicios.</p>}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="fila">
        <button type="button" className="btn" onClick={onCancelar}>
          Cancelar
        </button>
        <button type="submit" className="btn btn-cta" disabled={enviando}>
          {enviando ? "Guardando…" : "Crear usuario"}
        </button>
      </div>
    </form>
  );
}
