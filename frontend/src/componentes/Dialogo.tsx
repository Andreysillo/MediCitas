import { useEffect, useRef, type ReactNode } from "react";
import "../vistas/detalle.css";

type Props = Readonly<{
  titulo: string;
  onCerrar: () => void;
  /** Recibe `cerrar`, para que el contenido cierre la ventana (y devuelva el foco) tras guardar. */
  children: (cerrar: () => void) => ReactNode;
}>;

/** Ventana modal sobre <dialog> nativo: foco atrapado, Escape cierra y el foco vuelve a quien la abrió. */
export default function Dialogo({ titulo, onCerrar, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal();
  }, []);

  const cerrar = () => ref.current?.close();

  return (
    <dialog ref={ref} className="detalle" aria-labelledby="dialogo-titulo" onClose={onCerrar}>
      <div className="detalle-cuerpo">
        <header className="detalle-head">
          <h2 id="dialogo-titulo">{titulo}</h2>
          <button type="button" className="btn btn-icon" aria-label="Cerrar" onClick={cerrar}>
            ×
          </button>
        </header>
        {children(cerrar)}
      </div>
    </dialog>
  );
}
