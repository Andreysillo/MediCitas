# Etapa 1: compila el frontend. Etapa 2: nginx sirve los archivos y hace de gateway hacia las APIs.
# La imagen final no lleva Node ni node_modules, solo dist/.
FROM node:22-alpine AS compilar
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=compilar /app/dist /usr/share/nginx/html

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/salud || exit 1
