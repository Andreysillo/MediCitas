// Luz especular en el borde de los botones (.btn), inspirada en SpecularButton de React Bits. En vez de un
// contexto WebGL por botón (los navegadores admiten unos 16 y la app tiene decenas de botones), un solo
// listener calcula para cada botón el ángulo hacia el cursor y qué tan cerca está; el borde de luz es CSS.

const ALCANCE = 250; // px desde el borde en los que la luz empieza a seguir al cursor

let cuadro = 0;

document.addEventListener(
  "pointermove",
  (e) => {
    if (e.pointerType === "touch") return;
    cancelAnimationFrame(cuadro);
    cuadro = requestAnimationFrame(() => {
      const botones = [...document.querySelectorAll<HTMLElement>(".btn")];
      // Primero se mide todo y después se escribe, para no forzar un layout por botón.
      const cajas = botones.map((b) => b.getBoundingClientRect());
      botones.forEach((boton, i) => {
        const caja = cajas[i];
        const dx = e.clientX - (caja.left + caja.width / 2);
        const dy = e.clientY - (caja.top + caja.height / 2);
        // Distancia al borde del botón (0 si el cursor está encima), no a su centro.
        const fuera = Math.hypot(Math.max(Math.abs(dx) - caja.width / 2, 0), Math.max(Math.abs(dy) - caja.height / 2, 0));
        const cerca = Math.max(0, 1 - fuera / ALCANCE);
        if (cerca === 0 && boton.style.getPropertyValue("--brillo") === "0") return;
        // conic-gradient mide desde arriba en sentido horario; atan2 desde la derecha: se suman 90°.
        boton.style.setProperty("--brillo-angulo", `${(Math.atan2(dy, dx) * 180) / Math.PI + 90}deg`);
        boton.style.setProperty("--brillo", cerca.toFixed(3));
      });
    });
  },
  { passive: true },
);
