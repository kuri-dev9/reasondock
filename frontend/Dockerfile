FROM node:20-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
ARG REACT_APP_UCE_DEBUG=false
ENV REACT_APP_UCE_DEBUG=$REACT_APP_UCE_DEBUG
RUN npm run build

# Production: nginx로 서빙
FROM nginx:alpine

COPY --from=builder /app/build /usr/share/nginx/html

# API 프록시 설정 (백엔드 8000 → /api)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
