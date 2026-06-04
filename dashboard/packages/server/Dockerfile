# Build Stage
ARG BASE_GOLANG_IMAGE=golang:1.25
ARG BASE_DEBIAN_IMAGE=debian:bookworm-slim

FROM ${BASE_GOLANG_IMAGE} AS builder

WORKDIR /app

# Copy dependencies first for caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary
# -ldflags="-w -s" reduces binary size
RUN CGO_ENABLED=1 GOOS=linux go build -ldflags="-w -s" -o mcibench-server ./cmd/server/main.go

# Runtime Stage
FROM ${BASE_DEBIAN_IMAGE}

WORKDIR /app

# Install runtime dependencies.
# curl is used by container health checks.
RUN apt-get update && apt-get install -y ca-certificates curl && rm -rf /var/lib/apt/lists/*

# Copy binary from builder
COPY --from=builder /app/mcibench-server .

# Copy config directory (template)
COPY config/config.example.yaml ./config/config.yaml

# Set environment variables
# Ensure server listens on all interfaces within container
ENV MCIBENCH_SERVER_PORT=8080
ENV MCIBENCH_SERVER_MODE=release

EXPOSE 8080

# Run the server
CMD ["./mcibench-server"]
