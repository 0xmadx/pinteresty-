# Build stage
FROM golang:1.21-alpine AS builder

WORKDIR /app

# Install git for downloading dependencies
RUN apk add --no-cache git

# Download Go modules
COPY go.mod ./

COPY . .

# Generate go.sum and download modules
RUN go mod tidy

# Build the Go app statically
RUN CGO_ENABLED=0 GOOS=linux go build -o cookie_server main.go

# Final stage
FROM alpine:latest  

WORKDIR /root/

# Copy the Pre-built binary file from the previous stage
COPY --from=builder /app/cookie_server .

# Expose port 8000 to the outside world
EXPOSE 8000

# Command to run the executable
CMD ["./cookie_server"]
