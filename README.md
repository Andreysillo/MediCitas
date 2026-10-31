# MediCitas

## Probar el frontend (temporal)

> Instrucciones provisionales mientras no existen el backend ni el `docker compose`. Por ahora el frontend usa datos de prueba en memoria.

Requisito: Node.js 22 o superior.

```bash
cd frontend
npm install      # solo la primera vez o cuando cambie package.json
npm run dev      # abre http://localhost:5173
```

- La raíz (`#/`) es la landing promocional (producto ficticio). El logo de la barra lateral regresa a ella.
- **"Probar la demo"** abre el ingreso: se elige rol, clínica y usuario de prueba. Dentro solo aparece lo que ese rol puede ver, como pasará luego con el token de Keycloak. **"Cambiar de rol"** vuelve a esa pantalla y **"Salir"** regresa a la landing.
- Los cambios hechos en la página viven en memoria: al recargar vuelven los datos de prueba.
- `npm run build` verifica los tipos y compila. Conviene correrlo antes de hacer commit.
