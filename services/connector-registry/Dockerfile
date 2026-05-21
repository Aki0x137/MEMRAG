FROM golang:1.22-alpine AS builder

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git

# Copy go files
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o connector-registry ./cmd/main.go

# Final stage - distroless
FROM gcr.io/distroless/static:nonroot

WORKDIR /

COPY --from=builder /build/connector-registry /connector-registry

EXPOSE 8082

USER nonroot:nonroot

ENTRYPOINT ["/connector-registry"]
