package com.ticketing.payment.entity;

import jakarta.persistence.*;

import java.math.BigDecimal;
import java.time.Instant;

// The payment aggregate. Owned entirely by payment-service — booking-service
// or any other reader goes through the REST API, never the DB directly.
// Same three-layer enforcement pattern as Booking: named transition methods
// gate state changes, DB check constraint sits alongside, @Version prevents
// concurrent-transition races.
@Entity
@Table(
    name = "payments",
    uniqueConstraints = @UniqueConstraint(
        name = "uk_payments_session_key",
        columnNames = "payment_session_key"
    )
)
public class Payment {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // Client-supplied idempotency key (same shape as booking's
    // Idempotency-Key). Two calls with the same session key -> same
    // payment returned, gateway is not called twice.
    @Column(name = "payment_session_key", nullable = false, length = 64)
    private String paymentSessionKey;

    // The booking this payment is for. Loose reference — payment-service
    // does not validate this against booking-service. Truthfulness enforced
    // by the client (booking-service, which sends its own booking id).
    @Column(name = "booking_id", nullable = false)
    private Long bookingId;

    @Column(name = "holder_id", nullable = false)
    private String holderId;

    @Column(nullable = false, precision = 12, scale = 2)
    private BigDecimal amount;

    @Column(nullable = false, length = 3)
    private String currency;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private PaymentMethod method;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private PaymentStatus status = PaymentStatus.INITIATED;

    // The gateway's own reference for this payment. Nullable until auth
    // succeeds. Real gateways return their own opaque id; we store it so
    // subsequent capture/void/refund calls can reference the same charge.
    @Column(name = "gateway_ref", length = 128)
    private String gatewayRef;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "authorized_at")
    private Instant authorizedAt;

    @Column(name = "captured_at")
    private Instant capturedAt;

    @Column(name = "refunded_at")
    private Instant refundedAt;

    @Version
    private Long version;

    protected Payment() {
        // JPA no-arg
    }

    public Payment(String paymentSessionKey, Long bookingId, String holderId,
                   BigDecimal amount, String currency, PaymentMethod method) {
        this.paymentSessionKey = paymentSessionKey;
        this.bookingId = bookingId;
        this.holderId = holderId;
        this.amount = amount;
        this.currency = currency;
        this.method = method;
        this.status = PaymentStatus.INITIATED;
    }

    @PrePersist
    void assignCreatedAt() {
        this.createdAt = Instant.now();
    }

    // ---- State transitions — only way to write status ----

    public void markAuthorized(String gatewayRef) {
        expect(PaymentStatus.INITIATED, "markAuthorized");
        this.status = PaymentStatus.AUTHORIZED;
        this.gatewayRef = gatewayRef;
        this.authorizedAt = Instant.now();
    }

    public void markCaptured() {
        expect(PaymentStatus.AUTHORIZED, "markCaptured");
        this.status = PaymentStatus.CAPTURED;
        this.capturedAt = Instant.now();
    }

    // Auth-fail branch or explicit void from booking-service's rollback.
    // Valid from INITIATED (never got past gateway) or AUTHORIZED (voiding
    // a reserved auth). NOT valid from CAPTURED — that needs refund.
    public void markFailed(String reason) {
        if (status.isTerminal()) {
            throw new IllegalStateException(
                    "Cannot fail a payment already " + status + " (id=" + id + ")");
        }
        if (status == PaymentStatus.CAPTURED) {
            throw new IllegalStateException(
                    "Cannot fail a CAPTURED payment (id=" + id + "); use refund path");
        }
        this.status = PaymentStatus.FAILED;
    }

    public void markRefundPending() {
        expect(PaymentStatus.CAPTURED, "markRefundPending");
        this.status = PaymentStatus.REFUND_PENDING;
    }

    public void markRefunded() {
        expect(PaymentStatus.REFUND_PENDING, "markRefunded");
        this.status = PaymentStatus.REFUNDED;
        this.refundedAt = Instant.now();
    }

    private void expect(PaymentStatus required, String action) {
        if (status != required) {
            throw new IllegalStateException(
                    action + " requires status " + required
                    + " but was " + status + " (id=" + id + ")");
        }
    }

    // ---- Getters ----

    public Long getId() { return id; }
    public String getPaymentSessionKey() { return paymentSessionKey; }
    public Long getBookingId() { return bookingId; }
    public String getHolderId() { return holderId; }
    public BigDecimal getAmount() { return amount; }
    public String getCurrency() { return currency; }
    public PaymentMethod getMethod() { return method; }
    public PaymentStatus getStatus() { return status; }
    public String getGatewayRef() { return gatewayRef; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getAuthorizedAt() { return authorizedAt; }
    public Instant getCapturedAt() { return capturedAt; }
    public Instant getRefundedAt() { return refundedAt; }
    public Long getVersion() { return version; }
}
