package com.ticketing.payment.repository;

import com.ticketing.payment.entity.Payment;
import com.ticketing.payment.entity.PaymentStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface PaymentRepository extends JpaRepository<Payment, Long> {

    // Idempotency lookup — same shape as booking's findByIdempotencyKey.
    // Client's session key resolves to the same payment on any retry.
    Optional<Payment> findByPaymentSessionKey(String paymentSessionKey);

    // Used by the auth-expiry sweep to void authorizations older than the
    // configured window (payment.auth.window-hours).
    List<Payment> findByStatusAndAuthorizedAtBefore(PaymentStatus status, Instant before);
}
