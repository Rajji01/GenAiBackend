package com.ticketing.payment.controller;

import com.ticketing.payment.dto.AuthorizeRequest;
import com.ticketing.payment.dto.PaymentResponse;
import com.ticketing.payment.dto.RefundRequest;
import com.ticketing.payment.service.PaymentService;
import com.ticketing.payment.service.PaymentService.CreationResult;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/payments")
@RequiredArgsConstructor
public class PaymentController {

    private final PaymentService service;

    // Authorize (initiate) a payment. Idempotent on paymentSessionKey.
    // 201 for fresh; 200 for an idempotent retry.
    @PostMapping
    public ResponseEntity<PaymentResponse> authorize(@Valid @RequestBody AuthorizeRequest request) {
        CreationResult result = service.authorize(request);
        HttpStatus status = result.freshlyCreated() ? HttpStatus.CREATED : HttpStatus.OK;
        return ResponseEntity.status(status).body(result.response());
    }

    @PostMapping("/{id}/capture")
    public PaymentResponse capture(@PathVariable Long id) {
        return service.capture(id);
    }

    @PostMapping("/{id}/void")
    public PaymentResponse voidAuth(@PathVariable Long id) {
        return service.voidAuth(id);
    }

    @PostMapping("/{id}/refund")
    public PaymentResponse refund(@PathVariable Long id, @Valid @RequestBody RefundRequest request) {
        return service.refund(id, request.reason());
    }

    @GetMapping("/{id}")
    public PaymentResponse get(@PathVariable Long id) {
        return service.get(id);
    }
}
