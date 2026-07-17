FROM node:22-alpine AS dependencies

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

FROM dependencies AS development

COPY frontend ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
