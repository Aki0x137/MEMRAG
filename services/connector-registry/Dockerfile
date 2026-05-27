FROM golang:1.24-alpine AS builder

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git

# Copy go files
COPY . .

# Build the binaries
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o connector-registry ./cmd/main.go
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o migrate ./cmd/migrate/main.go

# Final stage - minimal runtime with healthcheck tooling
FROM alpine:3.20

RUN apk add --no-cache ca-certificates wget

WORKDIR /

COPY --from=builder /build/connector-registry /connector-registry
COPY --from=builder /build/migrate /migrate
COPY --from=builder /build/migrations /migrations
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8082

ENTRYPOINT ["/docker-entrypoint.sh"]
