import { useState } from "react";
import { citasPorEstado } from "../api";
import { ESTADO_NOMBRE, type EstadoCita } from "../api/dominio";
import { hoy, sumarDias } from "../fechas";
import { useDatos } from "../hooks";
import "./admin.css";
import "./reportes.css";

const ESTADOS = Object.keys(ESTADO_NOMBRE) as EstadoCita[];

export default function Reportes() {
  const [desde, setDesde] = useState(() => sumarDias(hoy(), -13));
  const [hasta, setHasta] = useState(hoy);
  const reporte = useDatos(() => citasPorEstado(desde, hasta), [desde, hasta]);

  const rango = (d: string, h: string) => () => {
    setDesde(d);
    setHasta(h);
  };

  const datos = reporte.error ? null : reporte.datos;

  return (
    <div className="vista">
      <div className="barra">
        <label className="field">
          <span>Desde</span>
          <input type="date" required value={desde} onChange={(e) => setDesde(e.target.value)} />
        </label>
        <label className="field">
          <span>Hasta</span>
          <input type="date" required value={hasta} onChange={(e) => setHasta(e.target.value)} />
        </label>
        <button type="button" className="btn" onClick={rango(sumarDias(hoy(), -13), hoy())}>
          Últimos 14 días
        </button>
        <button type="button" className="btn" onClick={rango(hoy(), sumarDias(hoy(), 13))}>
          Próximos 14 días
        </button>
      </div>

      {reporte.error && <p className="aviso aviso-error" role="alert">{reporte.error}</p>}

      {datos && (
        <section className="panel" aria-labelledby="h-rep">
          <h2 id="h-rep">Citas por estado</h2>
          <p className="total">
            <strong>{datos.total}</strong> {datos.total === 1 ? "cita" : "citas"} entre el {datos.desde} y el {datos.hasta}
          </p>
          <div className="tabla-scroll">
            <table className="tabla">
              <thead>
                <tr>
                  <th>Estado</th>
                  <th>Proporción</th>
                  <th className="num">Citas</th>
                  <th className="num">%</th>
                </tr>
              </thead>
              <tbody>
                {ESTADOS.map((e) => {
                  const n = datos.porEstado[e];
                  const pct = datos.total ? (n / datos.total) * 100 : 0;
                  return (
                    <tr key={e} data-estado={e}>
                      <td>
                        <span className="estado-pill" data-estado={e}>{ESTADO_NOMBRE[e]}</span>
                      </td>
                      <td className="celda-barra">
                        <div className="pista" aria-hidden="true">
                          {n > 0 && <div className="relleno" style={{ width: `${pct}%` }} />}
                        </div>
                      </td>
                      <td className="num">{n}</td>
                      <td className="num">{pct.toFixed(1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="panel-nota">
            Se cuentan todas las citas cuyo inicio cae en el rango, incluidas las canceladas y reprogramadas. En PostgreSQL es una sola consulta con <code>GROUP BY estado</code>.
          </p>
        </section>
      )}
    </div>
  );
}
