import { useState } from "react";
import { listarAuditoria, listarUsuarios } from "../api";
import { fechaCorta, fechaLocal, hora } from "../fechas";
import { useDatos } from "../hooks";
import { ROL_NOMBRE } from "../navigation";
import "./admin.css";

const RECURSO = { NOTA_CLINICA: "Nota clínica", CONTACTO_PACIENTE: "Datos de contacto" } as const;

export default function Bitacora() {
  const usuarios = useDatos(listarUsuarios);
  const [usuarioId, setUsuarioId] = useState("");
  const [paciente, setPaciente] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");

  const bitacora = useDatos(
    () => listarAuditoria({ usuarioId: usuarioId || undefined, paciente, desde: desde || undefined, hasta: hasta || undefined }),
    [usuarioId, paciente, desde, hasta],
  );
  const datos = bitacora.error ? null : bitacora.datos;

  return (
    <div className="vista">
      <div className="barra">
        <label className="field">
          <span>Usuario</span>
          <select value={usuarioId} onChange={(e) => setUsuarioId(e.target.value)}>
            <option value="">Todos</option>
            {usuarios.datos?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nombre} · {ROL_NOMBRE[u.rol]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Paciente</span>
          <input type="search" autoComplete="off" placeholder="Nombre o identificación" value={paciente} onChange={(e) => setPaciente(e.target.value)} />
        </label>
        <label className="field">
          <span>Desde</span>
          <input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        </label>
        <label className="field">
          <span>Hasta</span>
          <input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
        </label>
      </div>

      {bitacora.error && <p className="aviso aviso-error" role="alert">{bitacora.error}</p>}

      {datos && (
        <section className="panel" aria-label="Registros de auditoría">
          <p className="panel-nota">
            Mostrando {datos.registros.length} de {datos.total} registros, del más reciente al más antiguo. La bitácora solo se agrega: la aplicación no puede modificarla ni borrarla (I6).
          </p>
          {datos.registros.length === 0 ? (
            <p className="aviso">Ningún registro coincide con los filtros.</p>
          ) : (
            <div className="tabla-scroll">
              <table className="tabla">
                <thead>
                  <tr>
                    <th>Cuándo</th>
                    <th>Quién</th>
                    <th>Acción</th>
                    <th>Qué</th>
                    <th>Sobre el paciente</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.registros.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {fechaCorta(fechaLocal(new Date(r.ocurrido_en)))}, {hora(r.ocurrido_en)}
                      </td>
                      <td>
                        <strong>{r.usuario}</strong>
                        {r.rol && <span className="panel-nota"> · {ROL_NOMBRE[r.rol]}</span>}
                      </td>
                      <td>
                        <span className="etiqueta" data-tono={r.accion === "LECTURA" ? "lectura" : "escritura"}>
                          {r.accion === "LECTURA" ? "Lectura" : "Escritura"}
                        </span>
                      </td>
                      <td>{RECURSO[r.recurso]}</td>
                      <td>
                        {r.paciente} <span className="panel-nota">{r.identificacion}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
