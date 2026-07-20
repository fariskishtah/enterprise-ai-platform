FROM node:22-alpine AS dependencies

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

FROM dependencies AS development

COPY frontend ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM dependencies AS build

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY frontend ./
RUN npm run build

FROM nginx:1.28.0-alpine AS production

COPY infrastructure/nginx/frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
