FROM node:20-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

ARG REACT_APP_UCE_DEBUG=false
ARG REACT_APP_RCA_DEBUG=true
ARG REACT_APP_CHAT_DEBUG=true
ENV REACT_APP_UCE_DEBUG=$REACT_APP_UCE_DEBUG
ENV REACT_APP_RCA_DEBUG=$REACT_APP_RCA_DEBUG
ENV REACT_APP_CHAT_DEBUG=$REACT_APP_CHAT_DEBUG

COPY . .

# CRA는 정적 번들 생성 시점에 REACT_APP_* 값을 인라인 치환한다.
# 빌드 직전에 .env.production을 덮어써서 docker-compose build.args 값이
# 로컬 파일 유무와 무관하게 항상 production build에 반영되도록 한다.
RUN printf "REACT_APP_UCE_DEBUG=%s\nREACT_APP_RCA_DEBUG=%s\nREACT_APP_CHAT_DEBUG=%s\n" \
    "$REACT_APP_UCE_DEBUG" \
    "$REACT_APP_RCA_DEBUG" \
    "$REACT_APP_CHAT_DEBUG" \
    > .env.production \
    && npm run build

# Production: nginx로 서빙
FROM nginx:alpine

COPY --from=builder /app/build /usr/share/nginx/html

# API 프록시 설정 (백엔드 8000 → /api)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
