FROM node:24-alpine AS base

WORKDIR /app

COPY package.json package-lock.json* ./

RUN npm install

### DEVELOPMENT ###
FROM base AS development

ENV NODE_ENV=development

EXPOSE 4200

CMD ["npm", "start", "--", "--host", "0.0.0.0", "--poll", "2000"]

### PRODUCTION ###
