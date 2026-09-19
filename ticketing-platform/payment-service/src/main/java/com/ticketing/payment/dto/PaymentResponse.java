package com.ticketing.payment.dto;

import com.ticketing.payment.entity.Payment;
import com.ticketing.payment.entity.PaymentMethod;
import com.ticketing.payment.entity.PaymentStatus;

import java.math.BigDecimal;
import java.time.Instant;

// Wire shape. `version` deliberately omitted (internal concurrency detail
// only, same rule as SeatResponse + BookingResponse in the other services).
public record PaymentResponse(
        Long paymentId,
        Long bookingId,
        String holderId,
        BigDecimal amount,
        String currency,
        PaymentMethod method,
        PaymentStatus status,
        String gatewayRef,
        Instant createdAt,
        Instant authorizedAt,
        Instant capturedAt,
        Instant refundedAt
) {
    public static PaymentResponse from(Payment p) {
        return new PaymentResponse(
                p.getId(), p.getBookingId(), p.getHolderId(),
                p.getAmount(), p.getCurrency(), p.getMethod(),
                p.getStatus(), p.getGatewayRef(),
                p.getCreatedAt(), p.getAuthorizedAt(), p.getCapturedAt(), p.getRefundedAt());
    }
}
