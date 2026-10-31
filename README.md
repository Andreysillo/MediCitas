# MediCitas

## Probar el frontend (temporal)

> Instrucciones provisionales mientras no existen el backend ni el `docker compose`. Por ahora el frontend usa datos de prueba en memoria.

Requisito: Node.js 22 o superior.

```bash
cd frontend
npm install      # solo la primera vez o cuando cambie package.json
npm run dev      # abre http://localhost:5173
```

- La raíz (`#/`) es la landing promocional (producto ficticio). **"Probar la demo"** entra a la aplicación y el logo de la barra lateral regresa a la landing.
- Con **"Ver como"**, en la barra lateral, se cambia de usuario de prueba. Cada usuario tiene su clínica y su rol, como pasará luego con el token de Keycloak.
- Los cambios hechos en la página viven en memoria: al recargar vuelven los datos de prueba.
- `npm run build` verifica los tipos y compila. Conviene correrlo antes de hacer commit.
