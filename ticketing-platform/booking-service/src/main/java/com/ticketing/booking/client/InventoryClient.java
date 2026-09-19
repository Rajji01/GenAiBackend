package com.ticketing.booking.client;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.util.Map;

// The one and only place booking-service calls inventory-service.
// Encapsulates: base URL, timeout, correlation-id header forwarding,
// translating HTTP errors into one of two typed exceptions the saga can
// handle uniformly, and the Resilience4j retry + circuit breaker.
//
// The retry / circuit breaker are annotation-driven and share a single
// "inventory" instance across all three methods — they act as one
// dependency's health signal. Configuration lives in application.yml
// under `resilience4j.retry.instances.inventory` and
// `resilience4j.circuitbreaker.instances.inventory`.
//
// Fallback methods here don't gracefully degrade (a booking cannot
// fabricate a seat hold) — they translate a circuit-open state into an
// InventoryTransientException so the saga's existing FAILED-plus-compensate
// path picks it up. The circuit-breaker's job is to fail FAST when
// inventory is genuinely down, not to invent success.
@Component
public class InventoryClient {

    private static final Logger log = LoggerFactory.getLogger(InventoryClient.class);
    private static final String INVENTORY = "inventory"; // Resilience4j instance name

    private final RestClient restClient;

    public InventoryClient(RestClient inventoryRestClient) {
        this.restClient = inventoryRestClient;
    }

    @Retry(name = INVENTORY)
    @CircuitBreaker(name = INVENTORY, fallbackMethod = "holdFallback")
    public HoldResponse hold(long showId, long seatId, String holderId) {
        return invoke("hold", showId, seatId, () -> restClient.post()
                .uri("/shows/{showId}/seats/{seatId}/hold", showId, seatId)
                .body(Map.of("holderId", holderId))
                .retrieve()
                .body(HoldResponse.class));
    }

    @Retry(name = INVENTORY)
    @CircuitBreaker(name = INVENTORY, fallbackMethod = "confirmFallback")
    public ConfirmResponse confirm(long showId, long seatId, String holderId) {
        return invoke("confirm", showId, seatId, () -> restClient.post()
                .uri("/shows/{showId}/seats/{seatId}/confirm", showId, seatId)
                .body(Map.of("holderId", holderId))
                .retrieve()
                .body(ConfirmResponse.class));
    }

    // Compensation. Fire-and-forget for the saga's purposes — return type
    // is void because the saga doesn't care about the response, only that
    // this was attempted. A failure here surfaces via the exception which
    // the caller logs but doesn't re-raise (Week 1 already handles a
    // release-noop, and hold TTL is the ultimate safety net).
    @Retry(name = INVENTORY)
    @CircuitBreaker(name = INVENTORY, fallbackMethod = "releaseFallback")
    public void release(long showId, long seatId, String holderId) {
        invoke("release", showId, seatId, () -> {
            restClient.post()
                    .uri("/shows/{showId}/seats/{seatId}/release", showId, seatId)
                    .body(Map.of("holderId", holderId))
                    .retrieve()
                    .toBodilessEntity();
            return null;
        });
    }

    // ----- Resilience4j fallbacks (invoked only when the circuit opens) -----

    // Fallbacks throw the NON-transient base InventoryClientException on
    // purpose. Bug caught live 2026-09-18: throwing the transient subclass
    // made @Retry retry the CB-open fallback itself — wasted 600ms of
    // backoff per request even though the CB had just told us "fail fast."
    // The base exception is not in retry-exceptions, so Retry skips it —
    // CB-open == fast-fail, as intended. Aspect ordering default has Retry
    // outer / CB inner, so this exception-shape choice is the surgical fix.
    HoldResponse holdFallback(long showId, long seatId, String holderId, CallNotPermittedException open) {
        log.warn("inventory_circuit_open op=hold seatId={}", seatId);
        throw new InventoryClientException(0, "inventory circuit open for hold", open);
    }

    ConfirmResponse confirmFallback(long showId, long seatId, String holderId, CallNotPermittedException open) {
        log.warn("inventory_circuit_open op=confirm seatId={}", seatId);
        throw new InventoryClientException(0, "inventory circuit open for confirm", open);
    }

    void releaseFallback(long showId, long seatId, String holderId, CallNotPermittedException open) {
        log.warn("inventory_circuit_open op=release seatId={}", seatId);
        throw new InventoryClientException(0, "inventory circuit open for release", open);
    }

    // ----- HTTP → exception translation -----

    private <T> T invoke(String op, long showId, long seatId, java.util.function.Supplier<T> call) {
        try {
            return call.get();
        } catch (RestClientResponseException http) {
            HttpStatusCode code = http.getStatusCode();
            String body = truncate(http.getResponseBodyAsString());
            if (code.is5xxServerError()) {
                // Transient: same call could plausibly succeed on retry.
                log.warn("inventory_{}_5xx showId={} seatId={} status={} body={}",
                        op, showId, seatId, code.value(), body);
                throw new InventoryTransientException(code.value(),
                        "inventory " + op + " returned HTTP " + code.value(), http);
            }
            // 4xx (or any other non-5xx): don't retry — the call is well-
            // formed but the resource says no. Retrying won't help.
            log.warn("inventory_{}_4xx showId={} seatId={} status={} body={}",
                    op, showId, seatId, code.value(), body);
            throw new InventoryClientException(code.value(),
                    "inventory " + op + " returned HTTP " + code.value(), http);
        } catch (ResourceAccessException io) {
            // Connect timeout, read timeout, connection refused — all
            // transient by nature. A retry with a small backoff is the
            // whole point of Resilience4j being here.
            log.warn("inventory_{}_transport_error showId={} seatId={} reason={}",
                    op, showId, seatId, io.getMessage());
            throw new InventoryTransientException(0,
                    "inventory " + op + " transport error: " + io.getMessage(), io);
        }
    }

    private static String truncate(String s) {
        if (s == null) return "";
        return s.length() <= 200 ? s : s.substring(0, 200) + "…";
    }

    // Wire shapes match inventory-service's actual responses (see
    // HoldResponse / ConfirmResponse over there). Kept as local records
    // in this package so the two services aren't sharing a DTO jar.
    public record HoldResponse(Long seatId, String holderId, long ttlSeconds) {}
    public record ConfirmResponse(Long seatId, String holderId, String status) {}
}
