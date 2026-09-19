package com.ticketing.booking.client;

import com.fasterxml.jackson.annotation.JsonInclude;
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

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;

// booking-service's only path to payment-service. Same shape as
// InventoryClient: RestClient + Resilience4j (@Retry + @CircuitBreaker),
// exception-hierarchy-as-retry-policy (Transient subclass whitelisted,
// base ignored), fallback throws base non-retryable (Bug 6's fix).
@Component
public class PaymentClient {

    private static final Logger log = LoggerFactory.getLogger(PaymentClient.class);
    private static final String INSTANCE = "payment"; // Resilience4j instance name

    private final RestClient restClient;

    public PaymentClient(RestClient paymentRestClient) {
        this.restClient = paymentRestClient;
    }

    @Retry(name = INSTANCE)
    @CircuitBreaker(name = INSTANCE, fallbackMethod = "authorizeFallback")
    public PaymentResponse authorize(AuthorizeRequest req) {
        return invoke("authorize", () -> restClient.post()
                .uri("/payments")
                .body(req)
                .retrieve()
                .body(PaymentResponse.class));
    }

    @Retry(name = INSTANCE)
    @CircuitBreaker(name = INSTANCE, fallbackMethod = "captureFallback")
    public PaymentResponse capture(Long paymentId) {
        return invoke("capture", () -> restClient.post()
                .uri("/payments/{id}/capture", paymentId)
                .retrieve()
                .body(PaymentResponse.class));
    }

    @Retry(name = INSTANCE)
    @CircuitBreaker(name = INSTANCE, fallbackMethod = "voidFallback")
    public PaymentResponse voidAuth(Long paymentId) {
        return invoke("void", () -> restClient.post()
                .uri("/payments/{id}/void", paymentId)
                .retrieve()
                .body(PaymentResponse.class));
    }

    @Retry(name = INSTANCE)
    @CircuitBreaker(name = INSTANCE, fallbackMethod = "refundFallback")
    public PaymentResponse refund(Long paymentId, String reason) {
        return invoke("refund", () -> restClient.post()
                .uri("/payments/{id}/refund", paymentId)
                .body(Map.of("reason", reason))
                .retrieve()
                .body(PaymentResponse.class));
    }

    // Reader used by BookingRecoveryService — no @Retry / no CB because
    // a dangling-saga sweep failure isn't a saga step and can just retry
    // on the next sweep tick.
    public PaymentResponse getById(Long paymentId) {
        return invoke("get", () -> restClient.get()
                .uri("/payments/{id}", paymentId)
                .retrieve()
                .body(PaymentResponse.class));
    }

    // ---- Fallbacks: throw NON-retryable base type so Retry doesn't
    // retry the CB-open case (Bug 6 pattern) ----

    PaymentResponse authorizeFallback(AuthorizeRequest req, CallNotPermittedException open) {
        log.warn("payment_circuit_open op=authorize bookingId={}", req.bookingId());
        throw new PaymentClientException(0, "payment circuit open for authorize", open);
    }

    PaymentResponse captureFallback(Long paymentId, CallNotPermittedException open) {
        log.warn("payment_circuit_open op=capture paymentId={}", paymentId);
        throw new PaymentClientException(0, "payment circuit open for capture", open);
    }

    PaymentResponse voidFallback(Long paymentId, CallNotPermittedException open) {
        log.warn("payment_circuit_open op=void paymentId={}", paymentId);
        throw new PaymentClientException(0, "payment circuit open for void", open);
    }

    PaymentResponse refundFallback(Long paymentId, String reason, CallNotPermittedException open) {
        log.warn("payment_circuit_open op=refund paymentId={}", paymentId);
        throw new PaymentClientException(0, "payment circuit open for refund", open);
    }

    // ---- HTTP → exception translation ----

    private <T> T invoke(String op, java.util.function.Supplier<T> call) {
        try {
            return call.get();
        } catch (RestClientResponseException http) {
            HttpStatusCode code = http.getStatusCode();
            if (code.is5xxServerError()) {
                log.warn("payment_{}_5xx status={} body={}", op, code.value(),
                        truncate(http.getResponseBodyAsString()));
                throw new PaymentTransientException(code.value(),
                        "payment " + op + " returned HTTP " + code.value(), http);
            }
            log.warn("payment_{}_4xx status={} body={}", op, code.value(),
                    truncate(http.getResponseBodyAsString()));
            throw new PaymentClientException(code.value(),
                    "payment " + op + " returned HTTP " + code.value(), http);
        } catch (ResourceAccessException io) {
            log.warn("payment_{}_transport_error reason={}", op, io.getMessage());
            throw new PaymentTransientException(0,
                    "payment " + op + " transport error: " + io.getMessage(), io);
        }
    }

    private static String truncate(String s) {
        if (s == null) return "";
        return s.length() <= 200 ? s : s.substring(0, 200) + "…";
    }

    // ---- Wire shapes (kept local — no shared DTO jar) ----

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AuthorizeRequest(
            String paymentSessionKey,
            Long bookingId,
            String holderId,
            BigDecimal amount,
            String currency,
            String method
    ) {}

    public record PaymentResponse(
            Long paymentId,
            Long bookingId,
            String holderId,
            BigDecimal amount,
            String currency,
            String method,
            String status,
            String gatewayRef,
            Instant createdAt,
            Instant authorizedAt,
            Instant capturedAt,
            Instant refundedAt
    ) {}
}
