package com.ticketing.payment.dto;

import com.ticketing.payment.entity.PaymentMethod;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;

public record AuthorizeRequest(
        @NotBlank String paymentSessionKey,
        @NotNull @Positive Long bookingId,
        @NotBlank String holderId,
        @NotNull @DecimalMin(value = "0.01", inclusive = true) BigDecimal amount,
        @NotBlank @Pattern(regexp = "[A-Z]{3}") String currency,
        @NotNull PaymentMethod method
) {}
